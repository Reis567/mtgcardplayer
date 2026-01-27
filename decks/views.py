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
