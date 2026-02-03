from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import JsonResponse
import json
from accounts.views import get_current_player, get_tab_id
from cards.models import Card
from .models import Deck, DeckCard
from engine.validators import parse_decklist, validate_commander_deck


class ParseDecklistView(View):
    """API para parsear lista de cartas e retornar info"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            decklist_text = data.get('decklist', '').strip()

            if not decklist_text:
                return JsonResponse({'error': 'Lista vazia'})

            # Parse the decklist
            parsed, ignored = parse_decklist(decklist_text)

            if not parsed:
                return JsonResponse({'error': 'Nenhuma carta encontrada na lista'})

            # Look up each card in the database
            cards = []
            for qty, name in parsed:
                # Try exact match first
                card = Card.objects.filter(name__iexact=name).first()

                # If not found, try matching the front face of double-faced cards (Name // OtherName)
                if not card:
                    card = Card.objects.filter(name__istartswith=name + ' //').first()

                # If still not found, try a more flexible search (contains)
                if not card:
                    card = Card.objects.filter(name__icontains=name).first()

                card_data = {
                    'qty': qty,
                    'name': name,
                    'found': card is not None,
                }

                if card:
                    card_data.update({
                        'name': card.name,  # Use exact name from DB
                        'type_line': card.type_line or '',
                        'oracle_text': card.oracle_text or '',
                        'mana_cost': card.mana_cost or '',
                        'color_identity': card.color_identity or '',
                        'image_small': card.image_small or '',
                        'image_normal': card.image_normal or '',
                    })

                cards.append(card_data)

            return JsonResponse({
                'cards': cards,
                'ignored': ignored,
                'total': len(cards)
            })

        except json.JSONDecodeError:
            return JsonResponse({'error': 'JSON invalido'})
        except Exception as e:
            return JsonResponse({'error': str(e)})


class DeckListView(View):
    """Lista de todos os decks"""

    def get(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        # Mostrar todos os decks, com os do jogador atual primeiro
        decks = Deck.objects.all().select_related('commander', 'partner_commander', 'owner')

        # Separar decks próprios e de outros
        my_decks = [d for d in decks if d.owner_id == player.id]
        other_decks = [d for d in decks if d.owner_id != player.id]

        return render(request, 'decks/deck_list.html', {
            'my_decks': my_decks,
            'other_decks': other_decks,
            'player': player,
            'tab_id': tab_id
        })


class DeckImportView(View):
    """Importar deck de texto"""

    def get(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        return render(request, 'decks/deck_import.html', {
            'player': player,
            'tab_id': tab_id
        })

    def post(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        deck_name = request.POST.get('name', 'Meu Deck').strip()[:100]
        commander_name = request.POST.get('commander', '').strip()
        partner_name = request.POST.get('partner', '').strip() or None
        decklist_text = request.POST.get('decklist', '').strip()

        if not commander_name:
            return render(request, 'decks/deck_import.html', {
                'player': player,
                'tab_id': tab_id,
                'error': 'Nome do comandante e obrigatorio',
                'form_data': {
                    'name': deck_name,
                    'commander': commander_name,
                    'partner': partner_name,
                    'decklist': decklist_text
                }
            })

        if not decklist_text:
            return render(request, 'decks/deck_import.html', {
                'player': player,
                'tab_id': tab_id,
                'error': 'Lista de cartas e obrigatoria',
                'form_data': {
                    'name': deck_name,
                    'commander': commander_name,
                    'partner': partner_name,
                    'decklist': decklist_text
                }
            })

        # Funcao de lookup (suporta cartas de duas faces como "Name // OtherName")
        def card_lookup(name):
            card = Card.objects.filter(name__iexact=name).first()
            if not card:
                card = Card.objects.filter(name__istartswith=name + ' //').first()
            if not card:
                card = Card.objects.filter(name__icontains=name).first()
            if card:
                return {
                    'name': card.name,
                    'type_line': card.type_line,
                    'oracle_text': card.oracle_text,
                    'color_identity': card.color_identity,
                    'colors': card.colors,
                }
            return None

        # Parsear e validar
        parsed, _ = parse_decklist(decklist_text)
        result = validate_commander_deck(parsed, commander_name, card_lookup, partner_name)

        if not result.is_valid:
            return render(request, 'decks/deck_import.html', {
                'player': player,
                'tab_id': tab_id,
                'errors': result.errors,
                'warnings': result.warnings,
                'form_data': {
                    'name': deck_name,
                    'commander': commander_name,
                    'partner': partner_name,
                    'decklist': decklist_text
                }
            })

        # Criar deck - usar mesma logica de lookup para cartas de duas faces
        commander = Card.objects.filter(name__iexact=commander_name).first()
        if not commander:
            commander = Card.objects.filter(name__istartswith=commander_name + ' //').first()
        if not commander:
            commander = Card.objects.filter(name__icontains=commander_name).first()

        partner = None
        if partner_name:
            partner = Card.objects.filter(name__iexact=partner_name).first()
            if not partner:
                partner = Card.objects.filter(name__istartswith=partner_name + ' //').first()
            if not partner:
                partner = Card.objects.filter(name__icontains=partner_name).first()

        deck = Deck.objects.create(
            owner=player,
            name=deck_name,
            commander=commander,
            partner_commander=partner,
            color_identity=result.color_identity,
            raw_decklist=decklist_text,
            is_valid=True,
        )

        # Adicionar cartas - usar mesma logica de lookup para cartas de duas faces
        for qty, name in parsed:
            if name.lower() == commander_name.lower():
                continue
            if partner_name and name.lower() == partner_name.lower():
                continue

            card = Card.objects.filter(name__iexact=name).first()
            if not card:
                card = Card.objects.filter(name__istartswith=name + ' //').first()
            if not card:
                card = Card.objects.filter(name__icontains=name).first()
            if card:
                DeckCard.objects.create(deck=deck, card=card, quantity=qty)

        redirect_url = f'/decks/{deck.id}/?tab={tab_id}' if tab_id else f'/decks/{deck.id}/'
        return redirect(redirect_url)


class DeckDetailView(View):
    """Detalhes do deck"""

    def get(self, request, deck_id):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        # Permitir visualizar qualquer deck
        deck = get_object_or_404(Deck, id=deck_id)
        deck_cards = deck.cards.select_related('card').order_by('card__name')

        # Agrupar cartas por tipo
        cards_by_type = {
            'Creatures': [],
            'Instants': [],
            'Sorceries': [],
            'Enchantments': [],
            'Artifacts': [],
            'Planeswalkers': [],
            'Lands': [],
            'Other': []
        }

        # Dados para curva de mana
        mana_curve = {i: 0 for i in range(8)}  # 0-6 e 7+

        # Distribuicao de cores
        color_distribution = {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0, 'C': 0}

        for dc in deck_cards:
            card = dc.card
            qty = dc.quantity
            type_line = card.type_line.lower() if card.type_line else ''

            # Agrupar por tipo
            if 'creature' in type_line:
                cards_by_type['Creatures'].append(dc)
            elif 'instant' in type_line:
                cards_by_type['Instants'].append(dc)
            elif 'sorcery' in type_line:
                cards_by_type['Sorceries'].append(dc)
            elif 'enchantment' in type_line:
                cards_by_type['Enchantments'].append(dc)
            elif 'artifact' in type_line:
                cards_by_type['Artifacts'].append(dc)
            elif 'planeswalker' in type_line:
                cards_by_type['Planeswalkers'].append(dc)
            elif 'land' in type_line:
                cards_by_type['Lands'].append(dc)
            else:
                cards_by_type['Other'].append(dc)

            # Curva de mana (excluir lands)
            if 'land' not in type_line:
                cmc = int(card.cmc) if card.cmc else 0
                if cmc >= 7:
                    mana_curve[7] += qty
                else:
                    mana_curve[cmc] += qty

            # Distribuicao de cores
            if card.colors:
                for color in card.colors.split(','):
                    color = color.strip().upper()
                    if color in color_distribution:
                        color_distribution[color] += qty
            else:
                color_distribution['C'] += qty

        # Remover categorias vazias
        cards_by_type = {k: v for k, v in cards_by_type.items() if v}

        # Calcular max para escala do grafico
        max_mana_curve = max(mana_curve.values()) if mana_curve.values() else 1
        total_colored = sum(color_distribution.values()) or 1

        return render(request, 'decks/deck_detail.html', {
            'deck': deck,
            'deck_cards': deck_cards,
            'player': player,
            'is_owner': deck.owner_id == player.id,
            'card_count': deck.card_count(),
            'tab_id': tab_id,
            'cards_by_type': cards_by_type,
            'mana_curve': mana_curve,
            'max_mana_curve': max_mana_curve,
            'color_distribution': color_distribution,
            'total_colored': total_colored,
        })

    def post(self, request, deck_id):
        """Deletar deck - apenas o dono pode"""
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        # Apenas o dono pode deletar
        deck = get_object_or_404(Deck, id=deck_id, owner=player)

        if request.POST.get('action') == 'delete':
            deck.delete()
            redirect_url = f'/decks/?tab={tab_id}' if tab_id else '/decks/'
            return redirect(redirect_url)

        redirect_url = f'/decks/{deck_id}/?tab={tab_id}' if tab_id else f'/decks/{deck_id}/'
        return redirect(redirect_url)


class DeckBuilderView(View):
    """Construtor de Deck Inteligente - sugere cartas baseado no comandante"""

    # Categorias de cartas com patterns para deteccao
    CARD_CATEGORIES = {
        'ramp': {
            'name': 'Ramp',
            'target': 10,
            'patterns': [
                'add .* mana', 'search your library for .* land',
                'put .* land .* onto the battlefield', 'mana of any',
                'treasure token', 'sol ring'
            ],
            'description': 'Aceleracao de mana'
        },
        'removal': {
            'name': 'Removal',
            'target': 8,
            'patterns': [
                'destroy target', 'exile target', 'destroy all',
                'deals .* damage to', 'return .* to .* hand'
            ],
            'description': 'Remocao de ameacas'
        },
        'draw': {
            'name': 'Card Draw',
            'target': 10,
            'patterns': [
                'draw .* card', 'draws .* card', 'look at the top',
                'reveal .* draw', 'scry'
            ],
            'description': 'Compra de cartas'
        },
        'board_wipe': {
            'name': 'Board Wipes',
            'target': 3,
            'patterns': [
                'destroy all creature', 'exile all creature',
                'all creatures get -', 'deals .* damage to each creature'
            ],
            'description': 'Limpeza de campo'
        },
        'protection': {
            'name': 'Protection',
            'target': 5,
            'patterns': [
                'hexproof', 'indestructible', 'protection from',
                'counter target spell'
            ],
            'description': 'Protecao de permanentes'
        },
    }

    # Curva de mana ideal para commander
    IDEAL_MANA_CURVE = {
        0: 2, 1: 8, 2: 14, 3: 13, 4: 10, 5: 7, 6: 4, 7: 5,
    }

    def get_player_context(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        return {'player': player, 'tab_id': tab_id}

    def categorize_card(self, card):
        """Categoriza uma carta baseado em seus patterns"""
        import re
        categories = []
        oracle = (card.oracle_text or '').lower()

        for cat_id, cat_info in self.CARD_CATEGORIES.items():
            for pattern in cat_info['patterns']:
                if re.search(pattern, oracle, re.IGNORECASE):
                    categories.append(cat_id)
                    break
        return categories

    def find_synergy_cards(self, commander, color_identity, limit=20):
        """Encontra cartas que sinergizam com o comandante"""
        import re
        from django.db.models import Q, Min

        synergy_cards = []
        oracle = (commander.oracle_text or '').lower()

        # Extrair palavras-chave do comandante
        keywords = []
        mechanic_keywords = [
            'sacrifice', 'token', 'counter', 'graveyard', 'draw',
            'enters the battlefield', 'dies', 'attacks', '+1/+1'
        ]

        for kw in mechanic_keywords:
            if kw in oracle:
                keywords.append(kw)

        colors = [c.strip() for c in color_identity.split(',') if c.strip()]

        base_q = Q()
        if colors:
            for color in ['W', 'U', 'B', 'R', 'G']:
                if color not in colors:
                    base_q &= ~Q(color_identity__icontains=color)

        for keyword in keywords[:4]:
            keyword_q = Q(oracle_text__icontains=keyword)
            cards = Card.objects.filter(base_q & keyword_q).exclude(
                Q(type_line__icontains='Basic Land') | Q(id=commander.id)
            )

            unique_ids = cards.values('name').annotate(
                first_id=Min('id')
            ).values_list('first_id', flat=True)[:8]

            for card in Card.objects.filter(id__in=unique_ids):
                if card not in [s['card'] for s in synergy_cards]:
                    synergy_cards.append({
                        'card': card,
                        'reason': f'Sinergia: {keyword}',
                        'categories': self.categorize_card(card)
                    })

        return synergy_cards[:limit]

    def suggest_by_category(self, category_id, color_identity, exclude_ids, limit=8):
        """Sugere cartas de uma categoria especifica"""
        import re
        from django.db.models import Q, Min

        cat_info = self.CARD_CATEGORIES.get(category_id)
        if not cat_info:
            return []

        colors = [c.strip() for c in color_identity.split(',') if c.strip()]

        base_q = Q()
        if colors:
            for color in ['W', 'U', 'B', 'R', 'G']:
                if color not in colors:
                    base_q &= ~Q(color_identity__icontains=color)

        pattern_q = Q()
        for pattern in cat_info['patterns']:
            simple = pattern.replace('.*', ' ')
            simple = re.sub(r'[^a-zA-Z0-9\s\'-]', ' ', simple).strip()
            if simple and len(simple) > 2:
                pattern_q |= Q(oracle_text__icontains=simple)

        cards = Card.objects.filter(base_q & pattern_q).exclude(
            Q(type_line__icontains='Basic Land') | Q(id__in=exclude_ids)
        )

        unique_ids = cards.values('name').annotate(
            first_id=Min('id')
        ).values_list('first_id', flat=True)[:limit]

        return list(Card.objects.filter(id__in=unique_ids))

    def get(self, request):
        from django.db.models import Q

        context = self.get_player_context(request)
        if not context['player']:
            return redirect('login')

        commander_name = request.GET.get('commander', '').strip()
        selected_commander = None
        suggestions = {}
        synergy_cards = []
        color_identity = ''

        if commander_name:
            selected_commander = Card.objects.filter(
                Q(name__iexact=commander_name) |
                Q(name__istartswith=commander_name + ' //')
            ).filter(
                Q(type_line__icontains='Legendary') & Q(type_line__icontains='Creature') |
                Q(oracle_text__icontains='can be your commander')
            ).first()

            if selected_commander:
                color_identity = selected_commander.color_identity or ''
                exclude_ids = [selected_commander.id]

                synergy_cards = self.find_synergy_cards(
                    selected_commander, color_identity, limit=20
                )
                exclude_ids.extend([s['card'].id for s in synergy_cards])

                for cat_id, cat_info in self.CARD_CATEGORIES.items():
                    cat_cards = self.suggest_by_category(
                        cat_id, color_identity, exclude_ids, limit=8
                    )
                    suggestions[cat_id] = {
                        'name': cat_info['name'],
                        'target': cat_info['target'],
                        'description': cat_info['description'],
                        'cards': cat_cards
                    }
                    exclude_ids.extend([c.id for c in cat_cards])

        context.update({
            'commander_name': commander_name,
            'commander': selected_commander,
            'color_identity': color_identity,
            'synergy_cards': synergy_cards,
            'suggestions': suggestions,
            'categories': self.CARD_CATEGORIES,
            'ideal_curve': self.IDEAL_MANA_CURVE,
        })

        return render(request, 'decks/deck_builder.html', context)


class DeckAnalyzerView(View):
    """Analisador de Deck - analisa deck existente e da sugestoes"""

    RECOMMENDED_COUNTS = {
        'ramp': {'min': 8, 'ideal': 12, 'name': 'Ramp'},
        'removal': {'min': 6, 'ideal': 10, 'name': 'Removal'},
        'draw': {'min': 8, 'ideal': 12, 'name': 'Card Draw'},
        'board_wipe': {'min': 2, 'ideal': 4, 'name': 'Board Wipes'},
        'lands': {'min': 33, 'ideal': 37, 'name': 'Terrenos'},
    }

    KNOWN_COMBOS = [
        {
            'name': 'Dramatic Scepter',
            'cards': ['Isochron Scepter', 'Dramatic Reversal'],
            'description': 'Mana infinita'
        },
        {
            'name': 'Thoracle',
            'cards': ['Thassa\'s Oracle', 'Demonic Consultation'],
            'description': 'Vitoria instantanea'
        },
        {
            'name': 'Niv Curiosity',
            'cards': ['Niv-Mizzet', 'Curiosity'],
            'description': 'Dano infinito'
        },
    ]

    def get_player_context(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        return {'player': player, 'tab_id': tab_id}

    def categorize_card(self, card):
        import re
        categories = []
        oracle = (card.oracle_text or '').lower()
        type_line = (card.type_line or '').lower()

        if re.search(r'add .* mana|search .* land|treasure', oracle):
            categories.append('ramp')
        if re.search(r'destroy target|exile target|deals .* damage to', oracle):
            categories.append('removal')
        if re.search(r'draw .* card|draws .* card|scry', oracle):
            categories.append('draw')
        if re.search(r'destroy all|exile all', oracle):
            categories.append('board_wipe')
        if 'land' in type_line:
            categories.append('lands')

        return categories

    def detect_combos(self, card_names):
        found = []
        names_lower = [n.lower() for n in card_names]

        for combo in self.KNOWN_COMBOS:
            cards_lower = [c.lower() for c in combo['cards']]
            if all(any(cc in cn for cn in names_lower) for cc in cards_lower):
                found.append(combo)
        return found

    def get(self, request, deck_id):
        context = self.get_player_context(request)
        if not context['player']:
            return redirect('login')

        deck = get_object_or_404(Deck, id=deck_id)
        deck_cards = deck.cards.select_related('card').all()

        analysis = {
            'mana_curve': {i: 0 for i in range(8)},
            'type_distribution': {},
            'color_distribution': {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0, 'C': 0},
            'category_counts': {k: 0 for k in self.RECOMMENDED_COUNTS.keys()},
            'avg_cmc': 0,
            'total_cards': deck.card_count(),
        }

        total_cmc = 0
        non_land_count = 0
        card_names = [deck.commander.name]

        for dc in deck_cards:
            card = dc.card
            qty = dc.quantity
            type_line = (card.type_line or '').lower()
            card_names.append(card.name)

            if 'land' not in type_line:
                cmc = int(card.cmc) if card.cmc else 0
                total_cmc += cmc * qty
                non_land_count += qty
                analysis['mana_curve'][min(cmc, 7)] += qty

            main_type = 'Other'
            for t in ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Planeswalker', 'Land']:
                if t.lower() in type_line:
                    main_type = t
                    break
            analysis['type_distribution'][main_type] = analysis['type_distribution'].get(main_type, 0) + qty

            if card.colors:
                for color in card.colors.split(','):
                    color = color.strip().upper()
                    if color in analysis['color_distribution']:
                        analysis['color_distribution'][color] += qty
            else:
                analysis['color_distribution']['C'] += qty

            for cat in self.categorize_card(card):
                if cat in analysis['category_counts']:
                    analysis['category_counts'][cat] += qty

        analysis['avg_cmc'] = round(total_cmc / non_land_count, 2) if non_land_count > 0 else 0

        found_combos = self.detect_combos(card_names)

        alerts = []
        warnings = []

        for cat_id, rec in self.RECOMMENDED_COUNTS.items():
            count = analysis['category_counts'].get(cat_id, 0)
            if count < rec['min']:
                alerts.append(f"Faltam {rec['name']}: {count}/{rec['min']} minimo")
            elif count < rec['ideal']:
                warnings.append(f"{rec['name']} abaixo do ideal: {count}/{rec['ideal']}")

        if analysis['avg_cmc'] > 3.5:
            alerts.append(f"CMC medio muito alto: {analysis['avg_cmc']}")
        if analysis['total_cards'] < 100:
            alerts.append(f"Deck incompleto: {analysis['total_cards']}/100 cartas")

        context.update({
            'deck': deck,
            'analysis': analysis,
            'recommendations': self.RECOMMENDED_COUNTS,
            'alerts': alerts,
            'warnings': warnings,
            'found_combos': found_combos,
            'max_curve': max(analysis['mana_curve'].values()) or 1,
            'total_colored': sum(analysis['color_distribution'].values()) or 1,
        })

        return render(request, 'decks/deck_analyzer.html', context)


class ManaBaseGeneratorView(View):
    """Gerador de Mana Base"""

    def get_player_context(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        return {'player': player, 'tab_id': tab_id}

    def calculate_color_needs(self, deck_cards, commander):
        color_pips = {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0}

        if commander.mana_cost:
            for c in commander.mana_cost:
                if c.upper() in color_pips:
                    color_pips[c.upper()] += 2

        for dc in deck_cards:
            mana_cost = dc.card.mana_cost or ''
            for c in mana_cost:
                if c.upper() in color_pips:
                    color_pips[c.upper()] += dc.quantity

        return color_pips

    def suggest_lands(self, colors, color_pips, total_lands=37):
        from django.db.models import Q, Min

        suggestions = {'basics': {}, 'duals': [], 'utility': []}

        total_pips = sum(color_pips.values()) or 1
        basic_count = max(total_lands - 12, 15)

        basic_names = {'W': 'Plains', 'U': 'Island', 'B': 'Swamp', 'R': 'Mountain', 'G': 'Forest'}
        for color in colors:
            if color in color_pips:
                proportion = color_pips[color] / total_pips
                count = max(1, round(basic_count * proportion))
                suggestions['basics'][basic_names.get(color, 'Unknown')] = count

        # Buscar duals
        if len(colors) >= 2:
            dual_q = Q(type_line__icontains='Land')
            for color in colors[:2]:
                dual_q &= Q(color_identity__icontains=color)

            duals = Card.objects.filter(dual_q).exclude(
                type_line__icontains='Basic'
            )

            unique_ids = duals.values('name').annotate(
                first_id=Min('id')
            ).values_list('first_id', flat=True)[:10]

            for card in Card.objects.filter(id__in=unique_ids):
                suggestions['duals'].append(card)

        # Utility
        for name in ['Command Tower', 'Reliquary Tower', 'Rogue\'s Passage']:
            card = Card.objects.filter(name__iexact=name).first()
            if card:
                suggestions['utility'].append(card)

        return suggestions

    def calculate_pips_from_cards(self, cards_data):
        """Calcula pips de cor a partir de uma lista de cartas"""
        import re
        color_pips = {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0}

        for card_info in cards_data:
            mana_cost = card_info.get('mana_cost', '') or ''
            qty = card_info.get('quantity', 1)

            # Contar pips de cada cor
            for color in color_pips.keys():
                # Conta ocorrencias do simbolo de mana (ex: {W}, {U})
                count = len(re.findall(r'\{' + color + r'\}', mana_cost, re.IGNORECASE))
                color_pips[color] += count * qty

        return color_pips

    def parse_decklist(self, decklist_text):
        """Parse decklist text and return card info"""
        import re
        from django.db.models import Q

        lines = decklist_text.strip().split('\n')
        cards_data = []
        total_cards = 0
        land_count = 0
        non_land_count = 0

        for line in lines:
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('#'):
                continue

            # Parse "1 Card Name" or "1x Card Name"
            match = re.match(r'^(\d+)x?\s+(.+)$', line, re.IGNORECASE)
            if match:
                qty = int(match.group(1))
                card_name = match.group(2).strip()

                # Buscar a carta no banco
                card = Card.objects.filter(
                    Q(name__iexact=card_name) | Q(name__istartswith=card_name + ' //')
                ).first()

                if card:
                    is_land = 'land' in (card.type_line or '').lower()
                    cards_data.append({
                        'card': card,
                        'name': card.name,
                        'quantity': qty,
                        'mana_cost': card.mana_cost,
                        'is_land': is_land,
                        'color_identity': card.color_identity
                    })
                    total_cards += qty
                    if is_land:
                        land_count += qty
                    else:
                        non_land_count += qty

        return {
            'cards': cards_data,
            'total_cards': total_cards,
            'current_lands': land_count,
            'non_land_cards': non_land_count
        }

    def get(self, request):
        from django.db.models import Q

        context = self.get_player_context(request)
        if not context['player']:
            return redirect('login')

        deck_id = request.GET.get('deck')
        commander_name = request.GET.get('commander', '').strip()
        total_lands = int(request.GET.get('lands', 37))

        deck = None
        commander = None
        suggestions = None
        color_pips = {}
        colors = []

        if deck_id:
            deck = Deck.objects.filter(id=deck_id).first()
            if deck:
                commander = deck.commander
                colors = [c.strip() for c in (deck.color_identity or '').split(',') if c.strip()]
                deck_cards = deck.cards.select_related('card').all()
                color_pips = self.calculate_color_needs(deck_cards, commander)
                suggestions = self.suggest_lands(colors, color_pips, total_lands)

        elif commander_name:
            commander = Card.objects.filter(
                Q(name__iexact=commander_name) | Q(name__istartswith=commander_name + ' //')
            ).first()

            if commander:
                colors = [c.strip() for c in (commander.color_identity or '').split(',') if c.strip()]
                for c in colors:
                    color_pips[c] = 1
                suggestions = self.suggest_lands(colors, color_pips, total_lands)

        context.update({
            'deck': deck,
            'commander': commander,
            'commander_name': commander_name,
            'colors': colors,
            'color_pips': color_pips,
            'suggestions': suggestions,
            'total_lands': total_lands,
            'decklist_text': '',
            'decklist_analysis': None,
        })

        return render(request, 'decks/mana_base_generator.html', context)

    def post(self, request):
        """Handle decklist paste and analysis"""
        context = self.get_player_context(request)
        if not context['player']:
            return redirect('login')

        decklist_text = request.POST.get('decklist', '').strip()
        total_lands = int(request.POST.get('lands_count', 37))

        if not decklist_text:
            context.update({
                'decklist_text': decklist_text,
                'total_lands': total_lands,
            })
            return render(request, 'decks/mana_base_generator.html', context)

        # Parse the decklist
        parsed = self.parse_decklist(decklist_text)

        if not parsed['cards']:
            context.update({
                'decklist_text': decklist_text,
                'total_lands': total_lands,
            })
            return render(request, 'decks/mana_base_generator.html', context)

        # Calculate color pips from cards
        color_pips = self.calculate_pips_from_cards(parsed['cards'])

        # Determine colors with pips
        colors = [c for c, count in color_pips.items() if count > 0]

        # Generate land suggestions
        suggestions = self.suggest_lands(colors, color_pips, total_lands)

        context.update({
            'decklist_text': decklist_text,
            'decklist_analysis': parsed,
            'color_pips': color_pips,
            'colors': colors,
            'suggestions': suggestions,
            'total_lands': total_lands,
            'commander': None,
        })

        return render(request, 'decks/mana_base_generator.html', context)


class CardComparatorView(View):
    """Comparador de Cartas - Comparacao completa com insights"""

    def get_player_context(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        return {'player': player, 'tab_id': tab_id}

    def parse_power_toughness(self, value):
        """Parse power/toughness value, handling * and other special values"""
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            if '*' in str(value):
                return -1  # Variable
            return None

    def count_keywords(self, oracle_text):
        """Count important keywords in oracle text"""
        keywords = {
            'flying': 'Flying',
            'trample': 'Trample',
            'lifelink': 'Lifelink',
            'deathtouch': 'Deathtouch',
            'vigilance': 'Vigilance',
            'haste': 'Haste',
            'first strike': 'First Strike',
            'double strike': 'Double Strike',
            'hexproof': 'Hexproof',
            'indestructible': 'Indestructible',
            'menace': 'Menace',
            'reach': 'Reach',
            'flash': 'Flash',
            'ward': 'Ward',
        }
        found = []
        oracle_lower = (oracle_text or '').lower()
        for kw, display in keywords.items():
            if kw in oracle_lower:
                found.append(display)
        return found

    def analyze_card(self, card):
        """Analyze a single card and return structured data"""
        import re

        oracle = card.oracle_text or ''

        # Count colored pips
        mana_cost = card.mana_cost or ''
        pip_counts = {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0}
        for color in pip_counts:
            pip_counts[color] = len(re.findall(r'\{' + color + r'\}', mana_cost, re.IGNORECASE))

        # Card advantage indicators
        draws_cards = bool(re.search(r'draw.*card', oracle, re.IGNORECASE))
        has_removal = bool(re.search(r'destroy|exile|return.*to.*hand', oracle, re.IGNORECASE))
        has_ramp = bool(re.search(r'add.*mana|search.*land', oracle, re.IGNORECASE))
        has_protection = bool(re.search(r'hexproof|indestructible|protection from', oracle, re.IGNORECASE))

        return {
            'card': card,
            'cmc': float(card.cmc) if card.cmc else 0,
            'power': self.parse_power_toughness(card.power),
            'toughness': self.parse_power_toughness(card.toughness),
            'keywords': self.count_keywords(oracle),
            'keyword_count': len(self.count_keywords(oracle)),
            'pip_counts': pip_counts,
            'total_pips': sum(pip_counts.values()),
            'colors': [c.strip() for c in (card.colors or '').split(',') if c.strip()],
            'color_count': len([c for c in (card.colors or '').split(',') if c.strip()]),
            'rarity': card.rarity or 'common',
            'type_line': card.type_line or '',
            'is_creature': 'creature' in (card.type_line or '').lower(),
            'is_instant': 'instant' in (card.type_line or '').lower(),
            'is_sorcery': 'sorcery' in (card.type_line or '').lower(),
            'draws_cards': draws_cards,
            'has_removal': has_removal,
            'has_ramp': has_ramp,
            'has_protection': has_protection,
        }

    def generate_insights(self, analyzed_cards):
        """Generate insights comparing the cards"""
        insights = []

        if len(analyzed_cards) < 2:
            return insights

        # CMC comparison
        cmcs = [(a['card'].name, a['cmc']) for a in analyzed_cards]
        min_cmc = min(c[1] for c in cmcs)
        max_cmc = max(c[1] for c in cmcs)
        cheapest = [c[0] for c in cmcs if c[1] == min_cmc]

        if min_cmc != max_cmc:
            insights.append({
                'type': 'efficiency',
                'icon': '&#9889;',
                'title': 'Eficiencia de Mana',
                'text': f"<strong>{', '.join(cheapest)}</strong> e mais barato com CMC {int(min_cmc)}",
                'winner': cheapest[0]
            })

        # Keyword comparison (for creatures)
        creatures = [a for a in analyzed_cards if a['is_creature']]
        if len(creatures) >= 2:
            most_keywords = max(creatures, key=lambda x: x['keyword_count'])
            if most_keywords['keyword_count'] > 0:
                insights.append({
                    'type': 'abilities',
                    'icon': '&#11088;',
                    'title': 'Habilidades',
                    'text': f"<strong>{most_keywords['card'].name}</strong> tem mais keywords: {', '.join(most_keywords['keywords'][:4])}",
                    'winner': most_keywords['card'].name
                })

            # Power comparison
            powers = [(c['card'].name, c['power']) for c in creatures if c['power'] is not None and c['power'] >= 0]
            if powers:
                max_power = max(p[1] for p in powers)
                strongest = [p[0] for p in powers if p[1] == max_power]
                insights.append({
                    'type': 'combat',
                    'icon': '&#9876;',
                    'title': 'Poder de Combate',
                    'text': f"<strong>{', '.join(strongest)}</strong> tem maior power: {max_power}",
                    'winner': strongest[0]
                })

            # Toughness comparison
            toughnesses = [(c['card'].name, c['toughness']) for c in creatures if c['toughness'] is not None and c['toughness'] >= 0]
            if toughnesses:
                max_tough = max(t[1] for t in toughnesses)
                toughest = [t[0] for t in toughnesses if t[1] == max_tough]
                insights.append({
                    'type': 'defense',
                    'icon': '&#128737;',
                    'title': 'Resistencia',
                    'text': f"<strong>{', '.join(toughest)}</strong> tem maior toughness: {max_tough}",
                    'winner': toughest[0]
                })

        # Card advantage
        card_draw = [a for a in analyzed_cards if a['draws_cards']]
        if card_draw:
            names = [a['card'].name for a in card_draw]
            insights.append({
                'type': 'advantage',
                'icon': '&#128214;',
                'title': 'Card Advantage',
                'text': f"<strong>{', '.join(names)}</strong> oferece compra de cartas",
                'winner': names[0]
            })

        # Removal
        removal = [a for a in analyzed_cards if a['has_removal']]
        if removal:
            names = [a['card'].name for a in removal]
            insights.append({
                'type': 'removal',
                'icon': '&#128165;',
                'title': 'Remocao',
                'text': f"<strong>{', '.join(names)}</strong> pode remover ameacas",
                'winner': names[0]
            })

        # Mana efficiency (pip count vs cmc)
        pip_efficiency = []
        for a in analyzed_cards:
            if a['cmc'] > 0:
                eff = a['total_pips'] / a['cmc']
                pip_efficiency.append((a['card'].name, eff, a['total_pips']))

        if pip_efficiency:
            easiest = min(pip_efficiency, key=lambda x: x[1])
            if easiest[2] > 0:
                insights.append({
                    'type': 'casting',
                    'icon': '&#127775;',
                    'title': 'Facilidade de Conjuracao',
                    'text': f"<strong>{easiest[0]}</strong> e mais facil de conjurar ({easiest[2]} pips coloridos)",
                    'winner': easiest[0]
                })

        return insights

    def get(self, request):
        from django.db.models import Q

        context = self.get_player_context(request)

        card_names = request.GET.getlist('card')
        cards = []
        analyzed_cards = []

        for name in card_names[:4]:
            if name.strip():
                card = Card.objects.filter(
                    Q(name__iexact=name.strip()) | Q(name__istartswith=name.strip() + ' //')
                ).first()
                if card:
                    cards.append(card)
                    analyzed_cards.append(self.analyze_card(card))

        # Generate comparison table data
        comparison_table = []
        if len(analyzed_cards) >= 2:
            # CMC row
            cmcs = [a['cmc'] for a in analyzed_cards]
            min_cmc = min(cmcs)
            comparison_table.append({
                'label': 'Custo de Mana (CMC)',
                'values': [{'value': int(c) if c == int(c) else c, 'best': c == min_cmc} for c in cmcs],
                'best_idx': cmcs.index(min_cmc)
            })

            # Power (if creatures)
            powers = [a['power'] for a in analyzed_cards]
            if any(p is not None and p >= 0 for p in powers):
                display_powers = []
                for p in powers:
                    if p is None:
                        display_powers.append({'value': '-', 'best': False})
                    elif p == -1:
                        display_powers.append({'value': '*', 'best': False})
                    else:
                        display_powers.append({'value': p, 'best': False})
                max_power = max((p for p in powers if p is not None and p >= 0), default=0)
                for i, p in enumerate(powers):
                    if p == max_power and p >= 0:
                        display_powers[i]['best'] = True
                comparison_table.append({
                    'label': 'Power',
                    'values': display_powers,
                    'best_idx': powers.index(max_power) if max_power in powers else -1
                })

            # Toughness
            toughnesses = [a['toughness'] for a in analyzed_cards]
            if any(t is not None and t >= 0 for t in toughnesses):
                display_toughs = []
                for t in toughnesses:
                    if t is None:
                        display_toughs.append({'value': '-', 'best': False})
                    elif t == -1:
                        display_toughs.append({'value': '*', 'best': False})
                    else:
                        display_toughs.append({'value': t, 'best': False})
                max_tough = max((t for t in toughnesses if t is not None and t >= 0), default=0)
                for i, t in enumerate(toughnesses):
                    if t == max_tough and t >= 0:
                        display_toughs[i]['best'] = True
                comparison_table.append({
                    'label': 'Toughness',
                    'values': display_toughs,
                    'best_idx': toughnesses.index(max_tough) if max_tough in toughnesses else -1
                })

            # Keywords count
            kw_counts = [a['keyword_count'] for a in analyzed_cards]
            if any(k > 0 for k in kw_counts):
                max_kw = max(kw_counts)
                comparison_table.append({
                    'label': 'Keywords/Habilidades',
                    'values': [{'value': k, 'best': k == max_kw and k > 0} for k in kw_counts],
                    'best_idx': kw_counts.index(max_kw)
                })

            # Colored pips
            pips = [a['total_pips'] for a in analyzed_cards]
            min_pips = min(pips)
            comparison_table.append({
                'label': 'Pips Coloridos',
                'values': [{'value': p, 'best': p == min_pips} for p in pips],
                'best_idx': pips.index(min_pips)
            })

        # Generate insights
        insights = self.generate_insights(analyzed_cards)

        # Determine overall winner (most "wins")
        overall_winner = None
        if insights:
            winner_counts = {}
            for insight in insights:
                w = insight.get('winner')
                if w:
                    winner_counts[w] = winner_counts.get(w, 0) + 1
            if winner_counts:
                overall_winner = max(winner_counts, key=winner_counts.get)

        context.update({
            'cards': cards,
            'analyzed_cards': analyzed_cards,
            'card_names': card_names,
            'comparison_table': comparison_table,
            'insights': insights,
            'overall_winner': overall_winner,
        })

        return render(request, 'decks/card_comparator.html', context)
