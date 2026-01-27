from django.views.generic import ListView, DetailView
from django.views import View
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from .models import Card


class CardListView(ListView):
    """View simples de listagem de cards (legado)"""
    model = Card
    template_name = 'cards/card_list.html'
    context_object_name = 'cards'
    paginate_by = 50

    def get_queryset(self):
        queryset = Card.objects.all()

        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(oracle_text__icontains=search) |
                Q(type_line__icontains=search)
            )

        color = self.request.GET.get('color', '').strip().upper()
        if color:
            queryset = queryset.filter(colors__icontains=color)

        set_code = self.request.GET.get('set', '').strip().lower()
        if set_code:
            queryset = queryset.filter(set_code=set_code)

        rarity = self.request.GET.get('rarity', '').strip().lower()
        if rarity:
            queryset = queryset.filter(rarity=rarity)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['color'] = self.request.GET.get('color', '')
        context['set'] = self.request.GET.get('set', '')
        context['rarity'] = self.request.GET.get('rarity', '')
        context['total_cards'] = Card.objects.count()
        return context


class CardCatalogView(ListView):
    """Catalogo completo de cards com filtros avancados"""
    model = Card
    template_name = 'cards/card_catalog.html'
    context_object_name = 'cards'
    paginate_by = 48  # Multiplo de 6 para grid

    def get_queryset(self):
        queryset = Card.objects.all()

        # Busca por nome/texto
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(oracle_text__icontains=search)
            )

        # Filtro de cores - multiplas cores
        colors = self.request.GET.getlist('color')
        color_mode = self.request.GET.get('color_mode', 'include')  # include, exact, at_most

        if colors:
            if color_mode == 'exact':
                # Exatamente essas cores
                color_str = ','.join(sorted(colors))
                queryset = queryset.filter(color_identity=color_str)
            elif color_mode == 'at_most':
                # No maximo essas cores (pode ser subset)
                for card in queryset:
                    card_colors = set(card.color_identity.split(',')) if card.color_identity else set()
                    allowed = set(colors)
                    if not card_colors.issubset(allowed):
                        queryset = queryset.exclude(id=card.id)
            else:
                # Inclui essas cores (default)
                for c in colors:
                    queryset = queryset.filter(color_identity__icontains=c)

        # Filtro colorless
        if 'C' in colors or self.request.GET.get('colorless'):
            queryset = queryset.filter(Q(color_identity='') | Q(color_identity__isnull=True))

        # Filtro de tipo
        card_type = self.request.GET.get('type', '').strip()
        if card_type:
            queryset = queryset.filter(type_line__icontains=card_type)

        # Filtro de subtipo
        subtype = self.request.GET.get('subtype', '').strip()
        if subtype:
            queryset = queryset.filter(type_line__icontains=subtype)

        # Filtro de CMC (custo de mana convertido)
        cmc_min = self.request.GET.get('cmc_min', '').strip()
        cmc_max = self.request.GET.get('cmc_max', '').strip()
        if cmc_min:
            queryset = queryset.filter(cmc__gte=float(cmc_min))
        if cmc_max:
            queryset = queryset.filter(cmc__lte=float(cmc_max))

        # Filtro de poder (para criaturas)
        power_min = self.request.GET.get('power_min', '').strip()
        power_max = self.request.GET.get('power_max', '').strip()
        if power_min:
            try:
                queryset = queryset.filter(power__gte=str(int(power_min)))
            except ValueError:
                pass
        if power_max:
            try:
                queryset = queryset.filter(power__lte=str(int(power_max)))
            except ValueError:
                pass

        # Filtro de resistencia (para criaturas)
        tough_min = self.request.GET.get('tough_min', '').strip()
        tough_max = self.request.GET.get('tough_max', '').strip()
        if tough_min:
            try:
                queryset = queryset.filter(toughness__gte=str(int(tough_min)))
            except ValueError:
                pass
        if tough_max:
            try:
                queryset = queryset.filter(toughness__lte=str(int(tough_max)))
            except ValueError:
                pass

        # Filtro de raridade
        rarity = self.request.GET.getlist('rarity')
        if rarity:
            queryset = queryset.filter(rarity__in=rarity)

        # Filtro de set/colecao
        set_code = self.request.GET.get('set', '').strip().lower()
        if set_code:
            queryset = queryset.filter(set_code=set_code)

        # Busca no texto do oracle (keywords)
        oracle_text = self.request.GET.get('oracle', '').strip()
        if oracle_text:
            queryset = queryset.filter(oracle_text__icontains=oracle_text)

        # Ordenacao
        order = self.request.GET.get('order', 'name')
        order_dir = self.request.GET.get('dir', 'asc')

        order_fields = {
            'name': 'name',
            'cmc': 'cmc',
            'power': 'power',
            'toughness': 'toughness',
            'rarity': 'rarity',
            'set': 'set_code',
        }

        if order in order_fields:
            field = order_fields[order]
            if order_dir == 'desc':
                field = f'-{field}'
            queryset = queryset.order_by(field)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Parametros atuais para manter nos links de paginacao
        context['current_params'] = self.request.GET.copy()
        if 'page' in context['current_params']:
            del context['current_params']['page']

        # Valores atuais dos filtros
        context['q'] = self.request.GET.get('q', '')
        context['selected_colors'] = self.request.GET.getlist('color')
        context['color_mode'] = self.request.GET.get('color_mode', 'include')
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_subtype'] = self.request.GET.get('subtype', '')
        context['cmc_min'] = self.request.GET.get('cmc_min', '')
        context['cmc_max'] = self.request.GET.get('cmc_max', '')
        context['power_min'] = self.request.GET.get('power_min', '')
        context['power_max'] = self.request.GET.get('power_max', '')
        context['tough_min'] = self.request.GET.get('tough_min', '')
        context['tough_max'] = self.request.GET.get('tough_max', '')
        context['selected_rarities'] = self.request.GET.getlist('rarity')
        context['selected_set'] = self.request.GET.get('set', '')
        context['oracle'] = self.request.GET.get('oracle', '')
        context['order'] = self.request.GET.get('order', 'name')
        context['dir'] = self.request.GET.get('dir', 'asc')
        context['view_mode'] = self.request.GET.get('view', 'grid')

        # Estatisticas
        context['total_cards'] = Card.objects.count()
        context['result_count'] = self.get_queryset().count()

        # Sets disponiveis (para dropdown)
        context['available_sets'] = Card.objects.values('set_code', 'set_name').distinct().order_by('set_name')[:100]

        # Tipos de carta comuns
        context['card_types'] = [
            'Creature', 'Instant', 'Sorcery', 'Enchantment',
            'Artifact', 'Planeswalker', 'Land', 'Legendary'
        ]

        # Subtipos comuns
        context['subtypes'] = [
            'Human', 'Elf', 'Goblin', 'Dragon', 'Zombie', 'Angel', 'Demon',
            'Wizard', 'Warrior', 'Knight', 'Equipment', 'Aura', 'Vehicle'
        ]

        return context


class CardDetailView(View):
    """Pagina de detalhes de um card individual"""

    def get(self, request, card_id=None, card_name=None):
        if card_id:
            card = get_object_or_404(Card, id=card_id)
        elif card_name:
            # Busca por nome (pode ter multiplas versoes)
            card = Card.objects.filter(name__iexact=card_name).first()
            if not card:
                # Tenta busca parcial
                card = Card.objects.filter(name__icontains=card_name).first()
            if not card:
                from django.http import Http404
                raise Http404("Card nao encontrado")
        else:
            from django.http import Http404
            raise Http404("Card nao especificado")

        # Outras versoes do mesmo card (reprints)
        other_versions = Card.objects.filter(name=card.name).exclude(id=card.id).order_by('-set_code')[:10]

        # Cards relacionados (mesmo set ou tipo similar)
        related_cards = Card.objects.filter(
            Q(set_code=card.set_code) | Q(type_line__icontains=card.type_line.split()[0] if card.type_line else '')
        ).exclude(id=card.id).order_by('?')[:8]

        # Decks que usam este card
        from decks.models import DeckCard
        decks_using = DeckCard.objects.filter(card=card).select_related('deck', 'deck__owner', 'deck__commander')[:10]

        # Verificar legalidade (simplificado - baseado em se o card existe)
        formats_legal = {
            'Commander': True,  # Assumindo que todos sao legais em commander
            'Vintage': True,
            'Legacy': True,
            'Modern': card.set_code.lower() not in ['lea', 'leb', 'arn', 'atq', 'leg', 'drk', 'fem', 'hml'],
            'Standard': False,  # Seria necessario verificar rotacao
        }

        context = {
            'card': card,
            'other_versions': other_versions,
            'related_cards': related_cards,
            'decks_using': decks_using,
            'formats_legal': formats_legal,
        }

        return render(request, 'cards/card_detail.html', context)


class CardAutocompleteView(View):
    """API de autocomplete para busca de cards"""

    def get(self, request):
        q = request.GET.get('q', '').strip()
        if len(q) < 2:
            return JsonResponse({'results': []})

        cards = Card.objects.filter(name__icontains=q).values(
            'id', 'name', 'mana_cost', 'type_line', 'image_small'
        ).distinct()[:15]

        return JsonResponse({'results': list(cards)})


class RandomCardView(View):
    """Retorna um card aleatorio"""

    def get(self, request):
        card = Card.objects.order_by('?').first()
        if card:
            from django.shortcuts import redirect
            return redirect('card_detail', card_id=card.id)
        return JsonResponse({'error': 'Nenhum card encontrado'})
