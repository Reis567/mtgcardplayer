from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.http import JsonResponse
from accounts.views import get_current_player, get_tab_id
from cards.models import Card
from .models import Deck, DeckCard
from engine.validators import parse_decklist, validate_commander_deck


class DeckListView(View):
    """Lista de decks do jogador"""

    def get(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        decks = Deck.objects.filter(owner=player).select_related('commander', 'partner_commander')

        return render(request, 'decks/deck_list.html', {
            'decks': decks,
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

        # Funcao de lookup
        def card_lookup(name):
            card = Card.objects.filter(name__iexact=name).first()
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

        # Criar deck
        commander = Card.objects.filter(name__iexact=commander_name).first()
        partner = Card.objects.filter(name__iexact=partner_name).first() if partner_name else None

        deck = Deck.objects.create(
            owner=player,
            name=deck_name,
            commander=commander,
            partner_commander=partner,
            color_identity=result.color_identity,
            raw_decklist=decklist_text,
            is_valid=True,
        )

        # Adicionar cartas
        for qty, name in parsed:
            if name.lower() == commander_name.lower():
                continue
            if partner_name and name.lower() == partner_name.lower():
                continue

            card = Card.objects.filter(name__iexact=name).first()
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

        deck = get_object_or_404(Deck, id=deck_id, owner=player)
        deck_cards = deck.cards.select_related('card').order_by('card__name')

        return render(request, 'decks/deck_detail.html', {
            'deck': deck,
            'deck_cards': deck_cards,
            'player': player,
            'card_count': deck.card_count(),
            'tab_id': tab_id
        })

    def post(self, request, deck_id):
        """Deletar deck"""
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        deck = get_object_or_404(Deck, id=deck_id, owner=player)

        if request.POST.get('action') == 'delete':
            deck.delete()
            redirect_url = f'/decks/?tab={tab_id}' if tab_id else '/decks/'
            return redirect(redirect_url)

        redirect_url = f'/decks/{deck_id}/?tab={tab_id}' if tab_id else f'/decks/{deck_id}/'
        return redirect(redirect_url)
