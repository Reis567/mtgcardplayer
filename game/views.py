from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.http import JsonResponse
from accounts.views import get_current_player, get_tab_id
from .models import Game, GamePlayer, GameObject, GameAction, CommanderDamage
import random
import json


def setup_game(game):
    """Configura o estado inicial do jogo"""
    for game_player in game.players.all():
        # Criar objetos para todas as cartas do deck
        deck = game_player.deck

        # Comandante vai para zona de comando
        GameObject.objects.create(
            game=game,
            card=deck.commander,
            owner=game_player,
            controller=game_player,
            zone='command',
            is_commander=True
        )

        if deck.partner_commander:
            GameObject.objects.create(
                game=game,
                card=deck.partner_commander,
                owner=game_player,
                controller=game_player,
                zone='command',
                is_commander=True
            )

        # Cartas do deck vao para biblioteca (embaralhadas)
        deck_cards = list(deck.cards.select_related('card').all())
        random.shuffle(deck_cards)

        for i, deck_card in enumerate(deck_cards):
            for _ in range(deck_card.quantity):
                GameObject.objects.create(
                    game=game,
                    card=deck_card.card,
                    owner=game_player,
                    controller=game_player,
                    zone='library',
                    zone_position=i
                )

        # Comprar 7 cartas iniciais
        library_cards = GameObject.objects.filter(
            game=game,
            owner=game_player,
            zone='library'
        ).order_by('zone_position')[:7]

        for card in library_cards:
            card.zone = 'hand'
            card.save()

    # Definir jogador ativo (aleatorio)
    player_count = game.players.count()
    game.active_player_seat = random.randint(0, player_count - 1)
    game.turn_number = 1
    game.current_phase = 'main1'
    game.status = 'active'
    game.save()

    # Log de inicio
    GameAction.objects.create(
        game=game,
        action_type='game_start',
        display_text='Partida iniciada!',
        turn_number=1,
        phase='main1'
    )


class GameView(View):
    """View principal do jogo"""

    def get(self, request, game_id):
        tab_id = get_tab_id(request)
        player = get_current_player(request)
        if not player:
            return redirect('login')

        game = get_object_or_404(Game, id=game_id)
        game_player = GamePlayer.objects.filter(game=game, player=player).first()

        if not game_player:
            return redirect('lobby_list')

        # Buscar dados do jogo
        players = game.players.select_related('player', 'deck__commander').all()

        # Organizar objetos por zona e jogador
        all_objects = GameObject.objects.filter(game=game).select_related('card', 'owner', 'controller')

        zones_data = {}
        for gp in players:
            zones_data[gp.seat_position] = {
                'hand': [],
                'battlefield': [],
                'graveyard': [],
                'exile': [],
                'command': [],
                'library_count': 0
            }

        for obj in all_objects:
            seat = obj.controller.seat_position
            if obj.zone == 'library':
                zones_data[seat]['library_count'] += 1
            elif obj.zone in zones_data[seat]:
                zones_data[seat][obj.zone].append(obj)

        # Logs recentes
        recent_actions = GameAction.objects.filter(game=game).order_by('-timestamp')[:50]

        # Commander damage
        cmd_damage = {}
        for cd in CommanderDamage.objects.filter(game=game):
            key = (cd.target_player.seat_position, cd.source_player.seat_position)
            cmd_damage[key] = cd.damage

        return render(request, 'game/game.html', {
            'game': game,
            'game_player': game_player,
            'players': players,
            'zones_data': zones_data,
            'recent_actions': recent_actions,
            'cmd_damage': cmd_damage,
            'player': player,
            'tab_id': tab_id
        })

    def post(self, request, game_id):
        player = get_current_player(request)
        if not player:
            return JsonResponse({'error': 'Not authenticated'}, status=401)

        game = get_object_or_404(Game, id=game_id)
        game_player = GamePlayer.objects.filter(game=game, player=player).first()

        if not game_player:
            return JsonResponse({'error': 'Not in game'}, status=403)

        data = json.loads(request.body)
        action = data.get('action')

        if action == 'move_card':
            return self.handle_move_card(game, game_player, data)
        elif action == 'tap_card':
            return self.handle_tap_card(game, game_player, data)
        elif action == 'change_life':
            return self.handle_change_life(game, game_player, data)
        elif action == 'add_counter':
            return self.handle_counter(game, game_player, data, add=True)
        elif action == 'remove_counter':
            return self.handle_counter(game, game_player, data, add=False)
        elif action == 'next_phase':
            return self.handle_next_phase(game, game_player)
        elif action == 'next_turn':
            return self.handle_next_turn(game, game_player)
        elif action == 'draw_card':
            return self.handle_draw_card(game, game_player)
        elif action == 'shuffle_library':
            return self.handle_shuffle(game, game_player)
        elif action == 'concede':
            return self.handle_concede(game, game_player)

        return JsonResponse({'error': 'Unknown action'}, status=400)

    def handle_move_card(self, game, game_player, data):
        obj_id = data.get('object_id')
        new_zone = data.get('zone')

        obj = GameObject.objects.filter(id=obj_id, game=game).first()
        if not obj:
            return JsonResponse({'error': 'Object not found'}, status=404)

        old_zone = obj.zone
        obj.zone = new_zone
        obj.is_tapped = False
        obj.save()

        GameAction.objects.create(
            game=game,
            action_type='zone_change',
            player=game_player,
            data={'card': obj.card.name, 'from': old_zone, 'to': new_zone},
            display_text=f"{game_player.player.nickname} moveu {obj.card.name} de {old_zone} para {new_zone}",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True})

    def handle_tap_card(self, game, game_player, data):
        obj_id = data.get('object_id')

        obj = GameObject.objects.filter(id=obj_id, game=game, zone='battlefield').first()
        if not obj:
            return JsonResponse({'error': 'Object not found'}, status=404)

        obj.is_tapped = not obj.is_tapped
        obj.save()

        action = 'virou' if obj.is_tapped else 'desvirou'
        GameAction.objects.create(
            game=game,
            action_type='tap' if obj.is_tapped else 'untap',
            player=game_player,
            data={'card': obj.card.name},
            display_text=f"{game_player.player.nickname} {action} {obj.card.name}",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True, 'is_tapped': obj.is_tapped})

    def handle_change_life(self, game, game_player, data):
        target_seat = data.get('target_seat')
        delta = data.get('delta', 0)

        target = GamePlayer.objects.filter(game=game, seat_position=target_seat).first()
        if not target:
            return JsonResponse({'error': 'Player not found'}, status=404)

        old_life = target.life
        target.life += delta
        target.save()

        # Verificar derrota
        if target.life <= 0:
            target.is_alive = False
            target.has_lost = True
            target.save()

        GameAction.objects.create(
            game=game,
            action_type='life_change',
            player=game_player,
            data={'target': target.player.nickname, 'old': old_life, 'new': target.life},
            display_text=f"{target.player.nickname}: {old_life} -> {target.life}",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True, 'new_life': target.life})

    def handle_counter(self, game, game_player, data, add=True):
        obj_id = data.get('object_id')
        counter_type = data.get('counter_type', '+1/+1')

        obj = GameObject.objects.filter(id=obj_id, game=game).first()
        if not obj:
            return JsonResponse({'error': 'Object not found'}, status=404)

        counters = obj.counters or {}
        current = counters.get(counter_type, 0)

        if add:
            counters[counter_type] = current + 1
        else:
            counters[counter_type] = max(0, current - 1)

        obj.counters = counters
        obj.save()

        action = 'adicionou' if add else 'removeu'
        GameAction.objects.create(
            game=game,
            action_type='counter_change',
            player=game_player,
            data={'card': obj.card.name, 'counter': counter_type, 'add': add},
            display_text=f"{game_player.player.nickname} {action} marcador {counter_type} em {obj.card.name}",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True, 'counters': counters})

    def handle_next_phase(self, game, game_player):
        phases = ['untap', 'upkeep', 'draw', 'main1', 'combat_begin', 'combat_attackers',
                  'combat_blockers', 'combat_damage', 'combat_end', 'main2', 'end', 'cleanup']

        current_idx = phases.index(game.current_phase)
        next_idx = (current_idx + 1) % len(phases)
        game.current_phase = phases[next_idx]
        game.save()

        GameAction.objects.create(
            game=game,
            action_type='phase_change',
            player=game_player,
            display_text=f"Fase: {game.get_current_phase_display()}",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True, 'phase': game.current_phase})

    def handle_next_turn(self, game, game_player):
        player_count = game.players.filter(is_alive=True).count()
        alive_players = list(game.players.filter(is_alive=True).order_by('seat_position'))

        current_idx = next(
            (i for i, p in enumerate(alive_players) if p.seat_position == game.active_player_seat),
            0
        )
        next_idx = (current_idx + 1) % len(alive_players)

        game.active_player_seat = alive_players[next_idx].seat_position
        game.turn_number += 1
        game.current_phase = 'untap'
        game.save()

        # Reset lands played
        for gp in game.players.all():
            gp.lands_played_this_turn = 0
            gp.save()

        # Desvirar permanentes do jogador ativo
        active = game.get_active_player()
        GameObject.objects.filter(
            game=game,
            controller=active,
            zone='battlefield',
            is_tapped=True
        ).update(is_tapped=False)

        GameAction.objects.create(
            game=game,
            action_type='turn_change',
            player=game_player,
            display_text=f"Turno {game.turn_number} - {active.player.nickname}",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True, 'turn': game.turn_number, 'active_seat': game.active_player_seat})

    def handle_draw_card(self, game, game_player):
        library = GameObject.objects.filter(
            game=game,
            owner=game_player,
            zone='library'
        ).order_by('zone_position').first()

        if not library:
            # Deck vazio = derrota
            game_player.is_alive = False
            game_player.has_lost = True
            game_player.save()
            return JsonResponse({'error': 'No cards in library', 'lost': True}, status=400)

        library.zone = 'hand'
        library.save()

        GameAction.objects.create(
            game=game,
            action_type='draw',
            player=game_player,
            data={'card': library.card.name},
            display_text=f"{game_player.player.nickname} comprou uma carta",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True, 'card_id': str(library.id)})

    def handle_shuffle(self, game, game_player):
        library_cards = list(GameObject.objects.filter(
            game=game,
            owner=game_player,
            zone='library'
        ))

        random.shuffle(library_cards)

        for i, card in enumerate(library_cards):
            card.zone_position = i
            card.save()

        GameAction.objects.create(
            game=game,
            action_type='manual',
            player=game_player,
            display_text=f"{game_player.player.nickname} embaralhou a biblioteca",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        return JsonResponse({'success': True})

    def handle_concede(self, game, game_player):
        game_player.is_alive = False
        game_player.has_lost = True
        game_player.save()

        GameAction.objects.create(
            game=game,
            action_type='concede',
            player=game_player,
            display_text=f"{game_player.player.nickname} concedeu",
            turn_number=game.turn_number,
            phase=game.current_phase
        )

        # Verificar se ha vencedor
        alive = game.players.filter(is_alive=True)
        if alive.count() == 1:
            winner = alive.first()
            winner.has_won = True
            winner.save()
            game.winner = winner
            game.status = 'finished'
            game.save()

        return JsonResponse({'success': True})
