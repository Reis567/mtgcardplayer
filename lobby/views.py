from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count
from accounts.views import get_current_player, get_tab_id
from decks.models import Deck
from .models import Lobby, LobbyPlayer


class LobbyListView(View):
    """Lista de lobbies disponiveis"""

    def get(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)

        if not player:
            return redirect('login')

        # Remover jogador de qualquer lobby que esteja (ao voltar para a lista)
        LobbyPlayer.objects.filter(player=player).delete()

        # Limpar lobbies vazios
        empty_lobbies = Lobby.objects.filter(status='waiting').annotate(
            player_count_val=Count('players')
        ).filter(player_count_val=0)
        empty_lobbies.delete()

        lobbies = Lobby.objects.filter(
            status__in=['waiting', 'ready']
        ).prefetch_related('players__player')

        # Mostrar TODOS os decks válidos (compartilhados entre todos os jogadores)
        all_decks = Deck.objects.filter(is_valid=True).select_related('commander', 'owner')

        return render(request, 'lobby/lobby_list.html', {
            'lobbies': lobbies,
            'player': player,
            'player_decks': all_decks,  # Renomeado mas mantém compatibilidade com template
            'tab_id': tab_id
        })


class LobbyCreateView(View):
    """Criar novo lobby"""

    def post(self, request):
        tab_id = get_tab_id(request)
        player = get_current_player(request)

        if not player:
            return redirect('login')

        name = request.POST.get('name', '').strip()[:100]
        if not name:
            name = f'Partida de {player.nickname}'

        max_players = int(request.POST.get('max_players', 4))
        max_players = min(max(max_players, 2), 6)

        lobby = Lobby.objects.create(
            name=name,
            max_players=max_players,
        )

        LobbyPlayer.objects.create(lobby=lobby, player=player, seat_position=0)

        return redirect(f'/lobby/{lobby.id}/?tab={tab_id}' if tab_id else f'/lobby/{lobby.id}/')


class LobbyDetailView(View):
    """Detalhes do lobby / Sala de espera"""

    def get(self, request, lobby_id):
        tab_id = get_tab_id(request)
        player = get_current_player(request)

        # Debug logging
        print(f"[LobbyDetailView] tab_id={tab_id}, player={player.nickname if player else None}, player_id={player.id if player else None}")
        print(f"[LobbyDetailView] URL: {request.get_full_path()}")
        print(f"[LobbyDetailView] Session keys: {list(request.session.keys())}")

        if not player:
            return redirect('login')

        lobby = get_object_or_404(Lobby, id=lobby_id)

        # Se o jogo já começou, redirecionar
        if lobby.game:
            return redirect(f'/game/{lobby.game.id}/?tab={tab_id}' if tab_id else f'/game/{lobby.game.id}/')

        # Verificar se jogador esta no lobby
        lobby_player = LobbyPlayer.objects.filter(lobby=lobby, player=player).first()

        # Se nao esta, tentar entrar
        if not lobby_player:
            if lobby.status != 'waiting' or lobby.player_count() >= lobby.max_players:
                return redirect(f'/lobby/?tab={tab_id}' if tab_id else '/lobby/')

            # Atribuir próximo seat_position disponível
            existing_seats = set(lobby.players.values_list('seat_position', flat=True))
            next_seat = 0
            while next_seat in existing_seats:
                next_seat += 1

            lobby_player = LobbyPlayer.objects.create(
                lobby=lobby,
                player=player,
                seat_position=next_seat
            )

        # Mostrar TODOS os decks válidos (compartilhados entre todos os jogadores)
        all_decks = Deck.objects.filter(is_valid=True).select_related('commander', 'owner')

        return render(request, 'lobby/lobby_detail.html', {
            'lobby': lobby,
            'lobby_player': lobby_player,
            'player': player,
            'player_decks': all_decks,  # Todos os decks válidos
            'players': lobby.players.select_related('player', 'deck__commander'),
            'tab_id': tab_id
        })

    def post(self, request, lobby_id):
        tab_id = get_tab_id(request)
        player = get_current_player(request)

        if not player:
            return redirect('login')

        lobby = get_object_or_404(Lobby, id=lobby_id)
        lobby_player = get_object_or_404(LobbyPlayer, lobby=lobby, player=player)

        action = request.POST.get('action')
        redirect_url = f'/lobby/{lobby_id}/?tab={tab_id}' if tab_id else f'/lobby/{lobby_id}/'

        if action == 'select_deck':
            deck_id = request.POST.get('deck_id')
            if deck_id:
                # Permitir selecionar qualquer deck válido (compartilhado)
                deck = Deck.objects.filter(id=deck_id, is_valid=True).first()
                if deck:
                    lobby_player.deck = deck
                    lobby_player.is_ready = False  # Reset ready quando muda deck
                    lobby_player.save()

        elif action == 'toggle_ready':
            if lobby_player.deck:
                lobby_player.is_ready = not lobby_player.is_ready
                lobby_player.save()

        elif action == 'leave':
            lobby_player.delete()
            if lobby.player_count() == 0:
                lobby.delete()
            return redirect(f'/lobby/?tab={tab_id}' if tab_id else '/lobby/')

        elif action == 'start_game':
            if lobby.can_start():
                from game.models import Game, GamePlayer
                from game.views import setup_game

                game = Game.objects.create()
                lobby.game = game
                lobby.status = 'in_game'
                lobby.started_at = timezone.now()
                lobby.save()

                # Criar jogadores do jogo
                for lp in lobby.players.all():
                    GamePlayer.objects.create(
                        game=game,
                        player=lp.player,
                        deck=lp.deck,
                        seat_position=lp.seat_position
                    )

                # Setup inicial do jogo
                setup_game(game)

                return redirect(f'/game/{game.id}/?tab={tab_id}' if tab_id else f'/game/{game.id}/')

        return redirect(redirect_url)
