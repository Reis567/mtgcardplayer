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

    def get_player_context(self):
        """Helper para obter jogador atual da sessao/tab"""
        from accounts.views import get_current_player, get_tab_id
        return {
            'player': get_current_player(self.request),
            'tab_id': get_tab_id(self.request)
        }

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

        # Player context for navbar
        context.update(self.get_player_context())

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
        from accounts.views import get_current_player, get_tab_id

        player = get_current_player(request)
        tab_id = get_tab_id(request)

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
            'player': player,
            'tab_id': tab_id,
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


class CardAssistantView(View):
    """Assistente para encontrar cards similares baseado em mecanicas, tipo, cores, etc."""

    # Keywords mecanicos para matching (nome, patterns, peso)
    # Peso maior = mecanica mais especifica/importante
    MECHANIC_KEYWORDS = [
        # ===== CRIATURAS MODIFICADAS (tema especifico) =====
        ('modified_creatures', ['modified creature', 'modified permanent', 'each modified', 'modified you control'], 15),
        ('equipment_synergy', ['equipped creature', 'equip cost', 'whenever .* becomes equipped', 'equipment you control', 'equip \\{', 'attach', 'equipped with'], 12),
        ('aura_synergy', ['enchanted creature', 'enchant creature', 'whenever .* becomes enchanted', 'auras you control', 'aura spell', 'enchanted permanent'], 12),
        ('counter_plus', ['\\+1/\\+1 counter', 'put .* counter', 'with .* counter', 'enters .* counter', 'additional .* counter'], 10),
        ('counter_minus', ['-1/-1 counter', 'remove .* counter'], 8),
        ('counter_other', ['loyalty counter', 'charge counter', 'time counter', 'verse counter', 'lore counter'], 7),

        # ===== TRIGGERS DE ZONA =====
        ('etb', ['enters the battlefield', 'enters play', 'when .* enters', 'whenever .* enters'], 8),
        ('etb_tapped', ['enters .* tapped'], 5),
        ('ltb', ['leaves the battlefield', 'whenever .* leaves'], 7),
        ('death_trigger', ['when .* dies', 'whenever .* dies', 'whenever another .* dies', 'if .* would die'], 9),
        ('graveyard_trigger', ['whenever .* put into .* graveyard', 'card is put into your graveyard'], 8),
        ('cast_trigger', ['whenever you cast', 'when you cast', 'whenever .* casts'], 7),
        ('spell_trigger', ['whenever .* spell', 'instant or sorcery'], 6),

        # ===== RECURSAO/GRAVEYARD =====
        ('self_recursion', ['return .* from your graveyard to the battlefield', 'return this card from your graveyard', 'return .* from your graveyard to your hand'], 12),
        ('creature_recursion', ['return .* creature .* from .* graveyard', 'creature card from your graveyard', 'return target creature card'], 10),
        ('reanimator', ['put .* from .* graveyard .* onto the battlefield', 'reanimate'], 11),
        ('graveyard_matters', ['cards in your graveyard', 'for each card in your graveyard', 'graveyard have', 'exile .* from .* graveyard'], 8),
        ('escape_recursion', ['escape', 'from your graveyard'], 7),
        ('flashback', ['flashback', 'cast .* from your graveyard'], 8),
        ('unearth', ['unearth'], 7),

        # ===== COMBATE =====
        ('attack_trigger', ['whenever .* attacks', 'when .* attacks', 'attacking creature', 'attacks alone', 'attack each', 'must attack'], 8),
        ('combat_damage', ['deals combat damage', 'combat damage to a player', 'combat damage to an opponent'], 9),
        ('block_trigger', ['whenever .* blocks', 'when .* blocks', 'blocking creature', 'can block', "can't block"], 7),
        ('combat_phase', ['beginning of combat', 'end of combat', 'declare attackers', 'declare blockers'], 6),
        ('extra_combat', ['additional combat', 'extra combat phase'], 10),
        ('goad', ['goad', 'goaded'], 8),
        ('battalion', ['battalion', 'attacks with .* other'], 7),
        ('exalted', ['exalted', 'attacks alone'], 7),
        ('double_strike', ['double strike'], 8),
        ('first_strike', ['first strike'], 5),
        ('vigilance', ['vigilance'], 4),
        ('haste', ['haste'], 5),

        # ===== EVASAO =====
        ('flying', ['flying', 'has flying'], 5),
        ('trample', ['trample'], 5),
        ('menace', ['menace'], 5),
        ('unblockable', ["can't be blocked", 'unblockable', 'is unblockable'], 7),
        ('skulk', ['skulk'], 5),
        ('shadow', ['shadow'], 6),
        ('fear_intimidate', ['fear', 'intimidate', "can't be blocked except"], 6),
        ('reach', ['reach'], 4),

        # ===== DRAW/CARD ADVANTAGE =====
        ('draw', ['draw a card', 'draw cards', 'draws a card', 'draw two', 'draw three'], 7),
        ('draw_trigger', ['whenever you draw', 'when you draw', 'draw .* additional'], 9),
        ('looting', ['draw .* then discard', 'discard .* then draw'], 8),
        ('rummaging', ['discard .* draw'], 7),
        ('impulse_draw', ['exile .* top .* you may play', 'exile .* top .* you may cast', 'play .* from exile'], 9),
        ('card_selection', ['scry', 'look at the top', 'surveil', 'explore'], 6),
        ('tutor', ['search your library for', 'search your library .* put .* hand'], 9),
        ('tutor_top', ['search .* library .* put .* top'], 8),
        ('wheel', ['each player .* draws', 'each player discards .* hand', 'wheel'], 10),

        # ===== RAMP/MANA =====
        ('land_ramp', ['search .* library .* land', 'land .* onto the battlefield', 'put .* land .* onto'], 8),
        ('mana_dork', ['add .* mana', 'tap: add', '{t}: add'], 6),
        ('mana_rock', ['mana of any', 'any color', 'add one mana'], 5),
        ('treasure', ['treasure token', 'create .* treasure', 'treasures you control'], 7),
        ('cost_reduction', ['cost .* less', 'costs .* less', 'reduce .* cost', 'without paying'], 8),
        ('extra_land', ['play .* additional land', 'put .* land .* from your hand'], 8),
        ('landfall', ['landfall', 'whenever a land enters', 'land enters the battlefield'], 9),

        # ===== REMOVAL =====
        ('destroy', ['destroy target', 'destroy all', 'destroys'], 6),
        ('exile_removal', ['exile target', 'exile all', 'exiles'], 7),
        ('damage_removal', ['deals .* damage to', 'deal .* damage', 'damage to each'], 6),
        ('bounce', ['return .* to .* owner', "return .* to .* hand", 'bounce'], 6),
        ('tuck', ['put .* on the bottom', 'shuffle .* into'], 7),
        ('board_wipe', ['destroy all creature', 'exile all creature', 'all creatures get -', '-X/-X until'], 10),
        ('spot_removal', ['destroy target creature', 'exile target creature', 'target creature gets -'], 7),
        ('artifact_removal', ['destroy .* artifact', 'exile .* artifact'], 6),
        ('enchantment_removal', ['destroy .* enchantment', 'exile .* enchantment'], 6),
        ('planeswalker_removal', ['destroy .* planeswalker', 'damage to .* planeswalker'], 6),
        ('fight', ['fight', 'fights'], 6),
        ('deathtouch', ['deathtouch'], 6),

        # ===== COUNTERSPELLS/CONTROL =====
        ('counterspell', ['counter target spell', 'counter that spell', 'counter target .* spell'], 9),
        ('counter_creature', ['counter target creature'], 8),
        ('counter_noncreature', ['counter target noncreature'], 8),
        ('tax', ['pay .* more', 'costs .* more', 'unless .* pays'], 7),
        ('stax', ["can't .* more than", "opponents can't", "each player can't", 'players can.t'], 9),
        ('control_steal', ['gain control', 'exchange control', 'gains control', 'take control'], 9),
        ('copy', ['copy', 'copies', 'create a copy', 'becomes a copy', 'clone'], 8),
        ('redirect', ['change .* target', 'new target'], 6),

        # ===== PROTECTION =====
        ('hexproof', ['hexproof'], 7),
        ('shroud', ['shroud'], 6),
        ('indestructible', ['indestructible', 'gains indestructible'], 8),
        ('protection', ['protection from', 'has protection'], 7),
        ('ward', ['ward'], 6),
        ('regenerate', ['regenerate'], 5),
        ('totem_armor', ['totem armor'], 7),
        ('phase_out', ['phase out', 'phases out'], 6),

        # ===== TOKENS =====
        ('token_creation', ['create .* token', 'creates .* token', 'put .* token', 'tokens onto'], 8),
        ('token_copy', ['copy of .* creature', 'token .* copy'], 9),
        ('token_anthem', ['tokens you control', 'each token'], 7),
        ('populate', ['populate'], 8),
        ('treasure_tokens', ['treasure', 'create .* treasure'], 7),
        ('food_tokens', ['food', 'create .* food'], 6),
        ('clue_tokens', ['clue', 'investigate', 'create .* clue'], 6),

        # ===== LIFE/LIFEGAIN =====
        ('lifegain', ['gain .* life', 'gains .* life', 'you gain life'], 6),
        ('lifegain_trigger', ['whenever you gain life', 'when you gain life'], 9),
        ('lifelink', ['lifelink'], 6),
        ('life_payment', ['pay .* life', 'lose .* life'], 6),
        ('drain', ['lose .* life and you gain', 'loses .* life .* you gain', 'each opponent loses'], 8),
        ('extort', ['extort'], 7),

        # ===== SACRIFICE =====
        ('sacrifice_cost', ['sacrifice a', 'sacrifices a', 'as an additional cost.*sacrifice', ', sacrifice'], 8),
        ('sacrifice_trigger', ['whenever you sacrifice', 'whenever .* is sacrificed', 'whenever .* sacrifices'], 10),
        ('sacrifice_outlet', ['sacrifice another', 'you may sacrifice'], 8),
        ('aristocrats', ['whenever .* creature .* dies', 'whenever another creature', 'blood artist', 'drain'], 9),
        ('treasure_sac', ['sacrifice .* treasure', 'sacrifice a treasure'], 6),

        # ===== DISCARD =====
        ('discard', ['discard a card', 'discards a card', 'discard .* hand', 'discard .* cards'], 6),
        ('discard_trigger', ['whenever you discard', 'when you discard', 'whenever .* discards'], 8),
        ('madness', ['madness'], 9),
        ('opponent_discard', ['target player discards', 'opponent discards', 'each opponent discards'], 8),
        ('hand_attack', ['discard .* at random', "target opponent's hand", 'look at .* hand'], 7),

        # ===== MILL =====
        ('mill', ['mill', 'put .* cards .* into .* graveyard', 'cards from the top .* into'], 8),
        ('self_mill', ['mill yourself', 'your own .* graveyard'], 7),
        ('opponent_mill', ['target player mills', 'opponent mills', 'each opponent mills'], 7),

        # ===== PUMP/STATS =====
        ('power_boost', ['gets \\+', 'get \\+', '\\+1/\\+1', '\\+X/\\+X', '\\+2/\\+2'], 5),
        ('anthem', ['creatures you control get', 'other creatures you control', 'creatures you control have'], 9),
        ('lord', ['other .* get', 'other .* you control get'], 9),
        ('power_matters', ['power .* or greater', 'power .* or more', 'with power', 'total power'], 7),
        ('toughness_matters', ['toughness .* or greater', 'with toughness', 'total toughness'], 6),
        ('base_stats', ['base power and toughness'], 6),

        # ===== FLICKER/BLINK =====
        ('flicker', ['exile .* return .* to the battlefield', 'exile .* then return', 'flicker'], 9),
        ('blink', ['blink', 'exile .* return .* at', 'exile .* return .* next'], 9),
        ('etb_abuse', ['enters the battlefield .* again', 'reenter'], 8),

        # ===== SPELLSLINGER =====
        ('spellslinger', ['instant or sorcery', 'noncreature spell', 'whenever you cast .* instant', 'whenever you cast .* sorcery'], 9),
        ('prowess', ['prowess', 'whenever you cast a noncreature'], 8),
        ('magecraft', ['magecraft', 'whenever you cast or copy'], 9),
        ('storm', ['storm'], 10),
        ('spell_copy', ['copy .* instant', 'copy .* sorcery', 'copy that spell'], 9),

        # ===== TRIBAL =====
        ('tribal_lord', ['other .* you control', 'each .* you control'], 8),
        ('tribal_cost', ['.* spells .* cost .* less', '.* you cast cost'], 7),
        ('changeling', ['changeling', 'is every creature type'], 8),
        ('party', ['party', 'cleric.*rogue.*warrior.*wizard'], 8),

        # ===== COMMANDER SPECIFIC =====
        ('commander_matters', ['commander', 'command zone', 'commander tax', 'from the command zone'], 10),
        ('partner', ['partner'], 8),
        ('experience', ['experience counter'], 9),
        ('background', ['background'], 7),

        # ===== MISC THEMES =====
        ('proliferate', ['proliferate'], 10),
        ('untap', ['untap', 'untaps', 'doesn\'t untap'], 6),
        ('tap_ability', ['\\{t\\}:', 'tap .* creature', 'tap target'], 5),
        ('convoke', ['convoke'], 7),
        ('affinity', ['affinity'], 8),
        ('improvise', ['improvise'], 7),
        ('cascade', ['cascade'], 10),
        ('suspend', ['suspend'], 8),
        ('morph', ['morph', 'face down', 'face up', 'megamorph', 'manifest'], 8),
        ('mutate', ['mutate'], 9),
        ('transform', ['transform', 'transformed'], 7),
        ('meld', ['meld'], 8),
        ('energy', ['energy', '{e}'], 9),
        ('historic', ['historic', 'legendary .* artifact .* saga'], 7),
        ('saga', ['saga', 'lore counter'], 7),
        ('vehicles', ['vehicle', 'crew'], 8),
        ('planeswalker_synergy', ['planeswalker', 'loyalty', 'activate .* loyalty'], 7),
        ('ninjutsu', ['ninjutsu'], 9),
        ('cipher', ['cipher'], 7),
        ('overload', ['overload'], 7),
        ('kicker', ['kicker', 'kicked'], 6),
        ('flashback', ['flashback'], 8),
        ('buyback', ['buyback'], 7),
        ('retrace', ['retrace'], 7),
        ('jump_start', ['jump-start'], 7),
        ('foretell', ['foretell'], 7),
        ('adventure', ['adventure'], 8),
        ('companion', ['companion'], 8),
    ]

    def get_player_context(self, request):
        """Helper para obter jogador atual da sessao/tab"""
        from accounts.views import get_current_player, get_tab_id
        return {
            'player': get_current_player(request),
            'tab_id': get_tab_id(request)
        }

    def extract_mechanics(self, oracle_text):
        """Extrai mecanicas do texto do oracle com seus pesos"""
        import re
        if not oracle_text:
            return {}

        text = oracle_text.lower()
        found_mechanics = {}  # nome -> peso

        for mechanic_name, patterns, weight in self.MECHANIC_KEYWORDS:
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    found_mechanics[mechanic_name] = weight
                    break

        return found_mechanics

    def extract_keywords(self, oracle_text):
        """Extrai keywords especificas de MTG que nao estao nas mecanicas principais"""
        # Keywords que indicam estrategias/archetypes especificos
        KEYWORDS = [
            # Habilidades de evasao/combate secundarias
            'haste', 'vigilance', 'reach', 'deathtouch', 'first strike', 'double strike',
            'flash', 'defender', 'prowess', 'skulk',
            # Mechanics de set especificas que indicam sinergias
            'landfall', 'cascade', 'storm', 'modular', 'persist', 'undying',
            'evolve', 'exploit', 'fabricate', 'convoke', 'annihilator', 'infect',
            'extort', 'heroic', 'constellation', 'ferocious', 'raid', 'enrage',
            'explore', 'ascend', 'surveil', 'afterlife', 'adapt', 'mutate',
            'escape', 'foretell', 'ward', 'training', 'connive', 'alliance',
            'toxic', 'incubate', 'backup', 'bargain', 'offspring',
        ]

        if not oracle_text:
            return set()

        text = oracle_text.lower()
        found = set()
        for kw in KEYWORDS:
            if kw in text:
                found.add(kw)
        return found

    def calculate_similarity(self, reference_card, candidate_card, filters):
        """Calcula score de similaridade entre duas cartas"""
        score = 0
        reasons = []

        # 1. Mecanicas do oracle text (peso baseado na especificidade da mecanica)
        ref_mechanics = self.extract_mechanics(reference_card.oracle_text)
        cand_mechanics = self.extract_mechanics(candidate_card.oracle_text)

        # Calcular overlap com pesos
        mechanic_overlap = set(ref_mechanics.keys()) & set(cand_mechanics.keys())
        if mechanic_overlap:
            # Somar os pesos das mecanicas compartilhadas (usar o menor peso entre os dois)
            mechanic_score = sum(min(ref_mechanics[m], cand_mechanics[m]) for m in mechanic_overlap)
            score += min(mechanic_score, 60)  # Cap em 60 pontos

            # Mostrar as mecanicas mais importantes (com maior peso)
            sorted_mechanics = sorted(mechanic_overlap, key=lambda m: ref_mechanics[m], reverse=True)[:3]
            mechanic_names = [m.replace('_', ' ') for m in sorted_mechanics]
            reasons.append(f"Mecanicas: {', '.join(mechanic_names)}")

        # 2. Keywords de MTG (peso baixo - 15 pontos max, ja que mecanicas cobrem muito)
        ref_keywords = self.extract_keywords(reference_card.oracle_text)
        cand_keywords = self.extract_keywords(candidate_card.oracle_text)
        keyword_overlap = ref_keywords & cand_keywords
        if keyword_overlap:
            kw_score = len(keyword_overlap) * 3
            score += min(kw_score, 15)
            if len(reasons) < 2:  # So mostrar se nao tiver muitas mecanicas
                reasons.append(f"Keywords: {', '.join(list(keyword_overlap)[:2])}")

        # 3. Cor identity (peso medio - 15 pontos)
        ref_colors = set(reference_card.color_identity.split(',')) if reference_card.color_identity else set()
        cand_colors = set(candidate_card.color_identity.split(',')) if candidate_card.color_identity else set()
        color_overlap = ref_colors & cand_colors
        if ref_colors and cand_colors:
            if ref_colors == cand_colors:
                score += 15
                reasons.append("Cores identicas")
            elif color_overlap:
                score += len(color_overlap) * 5
                reasons.append(f"Cores em comum: {', '.join(color_overlap)}")

        # 4. Tipo de carta (peso medio - 15 pontos)
        ref_types = set(reference_card.type_line.lower().split()) if reference_card.type_line else set()
        cand_types = set(candidate_card.type_line.lower().split()) if candidate_card.type_line else set()

        # Tipos principais
        main_types = {'creature', 'instant', 'sorcery', 'enchantment', 'artifact', 'planeswalker', 'land'}
        ref_main = ref_types & main_types
        cand_main = cand_types & main_types

        if ref_main == cand_main:
            score += 10
            reasons.append(f"Mesmo tipo: {' '.join(ref_main)}")
        elif ref_main & cand_main:
            score += 5

        # Subtipos
        ref_subtypes = ref_types - main_types - {'legendary', '—', '-'}
        cand_subtypes = cand_types - main_types - {'legendary', '—', '-'}
        subtype_overlap = ref_subtypes & cand_subtypes
        if subtype_overlap:
            score += min(len(subtype_overlap) * 3, 5)
            reasons.append(f"Subtipos: {', '.join(list(subtype_overlap)[:2])}")

        # 5. CMC similar (peso baixo - 5 pontos)
        if abs(reference_card.cmc - candidate_card.cmc) <= 1:
            score += 5
        elif abs(reference_card.cmc - candidate_card.cmc) <= 2:
            score += 2

        # 6. Power/Toughness similar para criaturas (peso baixo - 5 pontos)
        if reference_card.power and candidate_card.power:
            try:
                ref_power = int(reference_card.power) if reference_card.power.isdigit() else 0
                cand_power = int(candidate_card.power) if candidate_card.power.isdigit() else 0
                if abs(ref_power - cand_power) <= 1:
                    score += 3
            except:
                pass

        if reference_card.toughness and candidate_card.toughness:
            try:
                ref_tough = int(reference_card.toughness) if reference_card.toughness.isdigit() else 0
                cand_tough = int(candidate_card.toughness) if candidate_card.toughness.isdigit() else 0
                if abs(ref_tough - cand_tough) <= 1:
                    score += 2
            except:
                pass

        # 7. Texto oracle similar (palavras chave especificas)
        if reference_card.oracle_text and candidate_card.oracle_text:
            ref_words = set(reference_card.oracle_text.lower().split())
            cand_words = set(candidate_card.oracle_text.lower().split())
            # Palavras significativas (excluir comuns)
            ignore = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'is', 'it', 'if', 'that', 'this', 'you', 'your'}
            ref_words = ref_words - ignore
            cand_words = cand_words - ignore
            overlap = len(ref_words & cand_words)
            if overlap > 5:
                score += min(overlap // 2, 10)

        return score, reasons

    def get(self, request):
        context = self.get_player_context(request)

        # Parametros de busca
        similar_to = request.GET.get('similar_to', '').strip()
        selected_card = None
        similar_cards = []

        # Filtros opcionais
        filters = {
            'colors': request.GET.getlist('color'),
            'type': request.GET.get('type', '').strip(),
            'subtype': request.GET.get('subtype', '').strip(),
            'cmc_min': request.GET.get('cmc_min', ''),
            'cmc_max': request.GET.get('cmc_max', ''),
            'power_min': request.GET.get('power_min', ''),
            'power_max': request.GET.get('power_max', ''),
            'rarity': request.GET.getlist('rarity'),
            'oracle': request.GET.get('oracle', '').strip(),
            'exclude_colors': request.GET.getlist('exclude_color'),
        }

        if similar_to:
            # Buscar o card de referencia
            selected_card = Card.objects.filter(
                Q(name__iexact=similar_to) | Q(name__icontains=similar_to)
            ).first()

            if selected_card:
                # Buscar cards candidatos (excluindo o proprio e duplicatas por nome)
                # Usar distinct no nome para evitar multiplas versoes da mesma carta
                from django.db.models import Min

                # Pegar apenas um ID por nome de carta (o menor, que geralmente e a versao original)
                unique_card_ids = Card.objects.exclude(
                    name=selected_card.name
                ).values('name').annotate(
                    first_id=Min('id')
                ).values_list('first_id', flat=True)

                queryset = Card.objects.filter(id__in=unique_card_ids)

                # Aplicar filtros opcionais
                if filters['colors']:
                    for c in filters['colors']:
                        queryset = queryset.filter(color_identity__icontains=c)

                if filters['exclude_colors']:
                    for c in filters['exclude_colors']:
                        queryset = queryset.exclude(color_identity__icontains=c)

                if filters['type']:
                    queryset = queryset.filter(type_line__icontains=filters['type'])

                if filters['subtype']:
                    queryset = queryset.filter(type_line__icontains=filters['subtype'])

                if filters['cmc_min']:
                    queryset = queryset.filter(cmc__gte=float(filters['cmc_min']))
                if filters['cmc_max']:
                    queryset = queryset.filter(cmc__lte=float(filters['cmc_max']))

                if filters['power_min']:
                    queryset = queryset.filter(power__gte=filters['power_min'])
                if filters['power_max']:
                    queryset = queryset.filter(power__lte=filters['power_max'])

                if filters['rarity']:
                    queryset = queryset.filter(rarity__in=filters['rarity'])

                if filters['oracle']:
                    queryset = queryset.filter(oracle_text__icontains=filters['oracle'])

                # Limitar para processamento
                candidates = queryset[:3000]

                # Calcular similaridade
                scored_cards = []
                seen_names = set()  # Backup para garantir unicidade

                for card in candidates:
                    # Pular se ja vimos essa carta (backup de seguranca)
                    if card.name in seen_names:
                        continue
                    seen_names.add(card.name)

                    score, reasons = self.calculate_similarity(selected_card, card, filters)
                    if score > 10:  # Threshold minimo para incluir mais cartas
                        scored_cards.append({
                            'card': card,
                            'score': score,
                            'reasons': reasons
                        })

                # Ordenar por score
                scored_cards.sort(key=lambda x: x['score'], reverse=True)
                similar_cards = scored_cards[:48]  # Top 48

        context.update({
            'similar_to': similar_to,
            'selected_card': selected_card,
            'similar_cards': similar_cards,
            'filters': filters,
            'card_types': [
                'Creature', 'Instant', 'Sorcery', 'Enchantment',
                'Artifact', 'Planeswalker', 'Land', 'Legendary'
            ],
            'subtypes': [
                'Human', 'Elf', 'Goblin', 'Dragon', 'Zombie', 'Angel', 'Demon',
                'Wizard', 'Warrior', 'Knight', 'Equipment', 'Aura', 'Vehicle'
            ],
        })

        return render(request, 'cards/card_assistant.html', context)
