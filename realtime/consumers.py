import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
import random


class LobbyConsumer(AsyncJsonWebsocketConsumer):
    """Consumer para sala de espera com sincronização em tempo real"""

    async def connect(self):
        self.lobby_id = self.scope['url_route']['kwargs']['lobby_id']
        self.group_name = f'lobby_{self.lobby_id}'
        self.player_id = None
        self.player_nickname = None
        self.tab_id = None

        # Pegar player_id da query string (mais confiável) ou da sessão
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        query_params = dict(param.split('=') for param in query_string.split('&') if '=' in param)

        # Tentar pegar player_id diretamente da query string
        if 'player_id' in query_params:
            self.player_id = query_params['player_id']
            print(f"[WS Lobby] Got player_id from query: {self.player_id}")

        # Tentar pegar tab_id
        if 'tab' in query_params:
            self.tab_id = query_params['tab']
            print(f"[WS Lobby] Got tab_id from query: {self.tab_id}")

        # Fallback: pegar da sessão usando tab_id
        session = self.scope.get('session')
        if session and not self.player_id:
            if self.tab_id:
                # Usar o player específico do tab
                self.player_id = session.get(f'player_{self.tab_id}')
                print(f"[WS Lobby] Got player_id from session with tab: {self.player_id}")
            else:
                # Fallback: tentar pegar de qualquer player_* na sessão
                for key in list(session.keys()):
                    if key.startswith('player_'):
                        self.player_id = session.get(key)
                        print(f"[WS Lobby] Got player_id from session fallback: {self.player_id}")
                        break

        # Buscar nickname
        if self.player_id:
            self.player_nickname = await self.get_player_nickname()

        print(f"[WS Lobby connect] Adding {self.channel_name} to group {self.group_name}")
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        print(f"[WS Lobby connect] Connection accepted for player {self.player_nickname} (id={self.player_id})")

        # Enviar estado inicial para quem conectou
        await self.send_lobby_state()

        # Notificar TODOS que alguém conectou (broadcast)
        print(f"[WS Lobby connect] Broadcasting lobby state to all in group")
        await self.broadcast_lobby_state()

    async def disconnect(self, close_code):
        # Remover jogador do lobby quando desconectar
        if self.player_id:
            await self.remove_player_from_lobby()

        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        # Notificar que alguém saiu
        await self.broadcast_lobby_state()

    @database_sync_to_async
    def remove_player_from_lobby(self):
        from lobby.models import Lobby, LobbyPlayer
        from accounts.models import PlayerProfile
        try:
            player = PlayerProfile.objects.get(id=self.player_id)
            lp = LobbyPlayer.objects.filter(lobby_id=self.lobby_id, player=player).first()
            if lp:
                lp.delete()
                print(f"[WS Lobby] Removed {player.nickname} from lobby {self.lobby_id}")

                # Verificar se lobby ficou vazio e deletar
                lobby = Lobby.objects.filter(id=self.lobby_id).first()
                if lobby and lobby.player_count() == 0:
                    print(f"[WS Lobby] Lobby {self.lobby_id} is empty, deleting...")
                    lobby.delete()
        except Exception as e:
            print(f"[WS Lobby] Error removing player: {e}")

    @database_sync_to_async
    def get_player_nickname(self):
        from accounts.models import PlayerProfile
        try:
            player = PlayerProfile.objects.get(id=self.player_id)
            return player.nickname
        except:
            return None

    @database_sync_to_async
    def get_lobby_state(self):
        from lobby.models import Lobby, LobbyPlayer
        try:
            lobby = Lobby.objects.get(id=self.lobby_id)
            players = []
            for lp in lobby.players.select_related('player', 'deck__commander').all():
                players.append({
                    'id': str(lp.player.id),
                    'nickname': lp.player.nickname,
                    'avatar_color': lp.player.avatar_color or '#e94560',
                    'is_ready': lp.is_ready,
                    'deck_name': lp.deck.name if lp.deck else None,
                    'commander_name': lp.deck.commander.name if lp.deck and lp.deck.commander else None,
                    'seat_position': lp.seat_position
                })

            return {
                'id': str(lobby.id),
                'name': lobby.name,
                'status': lobby.status,
                'player_count': len(players),
                'min_players': lobby.min_players,
                'max_players': lobby.max_players,
                'players': players,
                'can_start': lobby.can_start(),
                'game_id': str(lobby.game.id) if lobby.game else None
            }
        except Lobby.DoesNotExist:
            return None

    @database_sync_to_async
    def do_select_deck(self, player_id, deck_id):
        from lobby.models import LobbyPlayer
        from decks.models import Deck
        from accounts.models import PlayerProfile
        try:
            print(f"[WS select_deck] player_id={player_id}, deck_id={deck_id}")
            player = PlayerProfile.objects.get(id=player_id)
            print(f"[WS select_deck] Found player: {player.nickname}")
            # Permitir selecionar qualquer deck válido (compartilhado)
            deck = Deck.objects.get(id=deck_id, is_valid=True)
            print(f"[WS select_deck] Found deck: {deck.name}")
            lp = LobbyPlayer.objects.get(lobby_id=self.lobby_id, player=player)
            lp.deck = deck
            lp.is_ready = False  # Reset ready when changing deck
            lp.save()
            print(f"[WS select_deck] Deck selected successfully")
            return {'success': True, 'deck_name': deck.name}
        except Exception as e:
            print(f"[WS select_deck] Error: {e}")
            return {'success': False, 'error': str(e)}

    @database_sync_to_async
    def do_toggle_ready(self, player_id):
        from lobby.models import LobbyPlayer
        from accounts.models import PlayerProfile
        try:
            print(f"[WS toggle_ready] Looking for player_id={player_id}")
            player = PlayerProfile.objects.get(id=player_id)
            print(f"[WS toggle_ready] Found player: {player.nickname}")
            lp = LobbyPlayer.objects.get(lobby_id=self.lobby_id, player=player)
            print(f"[WS toggle_ready] Found LobbyPlayer, current is_ready={lp.is_ready}, deck={lp.deck}")
            if lp.deck:  # Só pode ficar pronto se tiver deck
                lp.is_ready = not lp.is_ready
                lp.save()
                print(f"[WS toggle_ready] Toggled is_ready to {lp.is_ready}")
                return {'success': True, 'is_ready': lp.is_ready}
            return {'success': False, 'error': 'Selecione um deck primeiro'}
        except Exception as e:
            print(f"[WS toggle_ready] Error: {e}")
            return {'success': False, 'error': str(e)}

    @database_sync_to_async
    def do_start_game(self):
        from lobby.models import Lobby
        from django.utils import timezone
        import random as rand

        # Importar modelos do jogo
        from game.models import Game as GameModel
        from game.models import GamePlayer as GamePlayerModel
        from game.models import GameObject as GameObjectModel
        from game.models import GameAction as GameActionModel

        try:
            lobby = Lobby.objects.get(id=self.lobby_id)

            if not lobby.can_start():
                return {'success': False, 'error': 'Nem todos os jogadores estão prontos'}

            if lobby.game:
                return {'success': True, 'game_id': str(lobby.game.id)}

            # Criar jogo
            game_instance = GameModel.objects.create(status='setup')

            # Criar jogadores do jogo
            game_players = []
            for i, lp in enumerate(lobby.players.select_related('player', 'deck').all()):
                lp.seat_position = i
                lp.save()
                gp = GamePlayerModel.objects.create(
                    game=game_instance,
                    player=lp.player,
                    deck=lp.deck,
                    seat_position=i,
                    life=40
                )
                game_players.append(gp)

            # Atualizar lobby
            lobby.game = game_instance
            lobby.status = 'in_game'
            lobby.started_at = timezone.now()
            lobby.save()

            # ========== SETUP GAME (inline) ==========
            for gp in game_players:
                player_deck = gp.deck

                # Comandante vai para zona de comando
                GameObjectModel.objects.create(
                    game=game_instance,
                    card=player_deck.commander,
                    owner=gp,
                    controller=gp,
                    zone='command',
                    is_commander=True
                )

                if player_deck.partner_commander:
                    GameObjectModel.objects.create(
                        game=game_instance,
                        card=player_deck.partner_commander,
                        owner=gp,
                        controller=gp,
                        zone='command',
                        is_commander=True
                    )

                # Cartas do deck vao para biblioteca (embaralhadas)
                deck_cards = list(player_deck.cards.select_related('card').all())
                rand.shuffle(deck_cards)

                for idx, deck_card in enumerate(deck_cards):
                    for _ in range(deck_card.quantity):
                        GameObjectModel.objects.create(
                            game=game_instance,
                            card=deck_card.card,
                            owner=gp,
                            controller=gp,
                            zone='library',
                            zone_position=idx
                        )

                # Comprar 7 cartas iniciais
                library_cards = GameObjectModel.objects.filter(
                    game=game_instance,
                    owner=gp,
                    zone='library'
                ).order_by('zone_position')[:7]

                for card_obj in library_cards:
                    card_obj.zone = 'hand'
                    card_obj.save()

            # Definir jogador ativo (aleatorio)
            player_count = len(game_players)
            game_instance.active_player_seat = rand.randint(0, player_count - 1)
            game_instance.turn_number = 1
            game_instance.current_phase = 'main1'
            game_instance.status = 'active'
            game_instance.save()

            # Log de inicio
            GameActionModel.objects.create(
                game=game_instance,
                action_type='game_start',
                display_text='Partida iniciada!',
                turn_number=1,
                phase='main1'
            )
            # ========== FIM SETUP GAME ==========

            return {'success': True, 'game_id': str(game_instance.id)}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}

    async def receive_json(self, content):
        action = content.get('action')
        # Priorizar player_id do conteúdo, depois da sessão
        player_id = content.get('player_id') or self.player_id

        # Debug
        print(f"[WS Lobby] Action: {action}, Player ID: {player_id}, Self Player ID: {self.player_id}")

        if action == 'chat':
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'chat_message',
                    'message': content.get('message', ''),
                    'sender': content.get('sender', 'Anonymous')
                }
            )

        elif action == 'select_deck':
            deck_id = content.get('deck_id')
            if player_id and deck_id:
                result = await self.do_select_deck(player_id, deck_id)
                if result['success']:
                    await self.broadcast_lobby_state()
                else:
                    await self.send_json({'type': 'error', 'message': result.get('error')})

        elif action == 'toggle_ready':
            if player_id:
                result = await self.do_toggle_ready(player_id)
                if result['success']:
                    await self.broadcast_lobby_state()
                else:
                    await self.send_json({'type': 'error', 'message': result.get('error')})

        elif action == 'start_game':
            result = await self.do_start_game()
            if result['success']:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        'type': 'game_starting',
                        'game_id': result['game_id']
                    }
                )
            else:
                await self.send_json({'type': 'error', 'message': result.get('error')})

        elif action == 'get_state':
            await self.send_lobby_state()

    async def send_lobby_state(self):
        state = await self.get_lobby_state()
        if state:
            await self.send_json({
                'type': 'lobby_state',
                'data': state
            })

    async def broadcast_lobby_state(self):
        state = await self.get_lobby_state()
        if state:
            print(f"[WS broadcast] Broadcasting to group {self.group_name}")
            print(f"[WS broadcast] Players: {[(p['nickname'], p['is_ready']) for p in state['players']]}")
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'lobby_update',
                    'data': state
                }
            )

    async def chat_message(self, event):
        await self.send_json({
            'type': 'chat',
            'message': event['message'],
            'sender': event['sender']
        })

    async def lobby_update(self, event):
        print(f"[WS lobby_update] Sending update to player {self.player_nickname} (id={self.player_id})")
        await self.send_json({
            'type': 'lobby_state',
            'data': event['data']
        })

    async def game_starting(self, event):
        await self.send_json({
            'type': 'game_starting',
            'game_id': event['game_id']
        })


class GameConsumer(AsyncJsonWebsocketConsumer):
    """Consumer principal do jogo com sincronização em tempo real"""

    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.group_name = f'game_{self.game_id}'
        self.player_id = None
        self.tab_id = None

        # Pegar player_id da query string (mais confiável)
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        query_params = dict(param.split('=') for param in query_string.split('&') if '=' in param)

        if 'player_id' in query_params:
            self.player_id = query_params['player_id']
            print(f"[WS Game] Got player_id from query: {self.player_id}")

        if 'tab' in query_params:
            self.tab_id = query_params['tab']
            print(f"[WS Game] Got tab_id from query: {self.tab_id}")

        # Fallback: pegar da sessão
        session = self.scope.get('session', {})
        if session and not self.player_id:
            if self.tab_id:
                self.player_id = session.get(f'player_{self.tab_id}')
            else:
                self.player_id = session.get('player_id')
            print(f"[WS Game] Got player_id from session: {self.player_id}")

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Enviar estado inicial
        await self.send_game_state()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    @database_sync_to_async
    def get_game_state(self):
        from game.models import Game, GamePlayer, GameObject, GameAction, CommanderDamage
        try:
            game = Game.objects.get(id=self.game_id)
            players = []
            zones_data = {}

            for gp in game.players.select_related('player', 'deck__commander').all():
                players.append({
                    'id': str(gp.id),
                    'player_id': str(gp.player.id),
                    'nickname': gp.player.nickname,
                    'avatar_color': gp.player.avatar_color or '#e94560',
                    'seat_position': gp.seat_position,
                    'life': gp.life,
                    'poison_counters': gp.poison_counters,
                    'is_alive': gp.is_alive,
                    'has_won': gp.has_won,
                    'commander_name': gp.deck.commander.name if gp.deck and gp.deck.commander else None
                })
                zones_data[gp.seat_position] = {
                    'hand': [],
                    'battlefield': [],
                    'graveyard': [],
                    'exile': [],
                    'command': [],
                    'library_count': 0
                }

            # Organizar objetos por zona
            for obj in GameObject.objects.filter(game=game).select_related('card', 'owner', 'controller'):
                seat = obj.controller.seat_position
                if obj.zone == 'library':
                    zones_data[seat]['library_count'] += 1
                elif obj.zone in zones_data[seat]:
                    # Handle tokens vs regular cards
                    if obj.is_token:
                        obj_data = {
                            'id': str(obj.id),
                            'card_id': None,
                            'name': obj.token_name,
                            'type_line': obj.token_type or '',
                            'mana_cost': '',
                            'oracle_text': obj.token_abilities or '',
                            'power': obj.token_power,
                            'toughness': obj.token_toughness,
                            'image_small': '',
                            'image_normal': '',
                            'is_tapped': obj.is_tapped,
                            'counters': obj.counters or {},
                            'is_commander': False,
                            'zone': obj.zone,
                            'battlefield_row': obj.battlefield_row,
                            'owner_seat': obj.owner.seat_position,
                            'controller_seat': obj.controller.seat_position,
                            'is_token': True,
                            'token_colors': obj.token_colors
                        }
                    else:
                        obj_data = {
                            'id': str(obj.id),
                            'card_id': str(obj.card.id) if obj.card else None,
                            'name': obj.card.name if obj.card else 'Unknown',
                            'type_line': (obj.card.type_line or '') if obj.card else '',
                            'mana_cost': (obj.card.mana_cost or '') if obj.card else '',
                            'oracle_text': (obj.card.oracle_text or '') if obj.card else '',
                            'power': obj.card.power if obj.card else None,
                            'toughness': obj.card.toughness if obj.card else None,
                            'image_small': (obj.card.image_small or '') if obj.card else '',
                            'image_normal': (obj.card.image_normal or '') if obj.card else '',
                            'is_tapped': obj.is_tapped,
                            'counters': obj.counters or {},
                            'is_commander': obj.is_commander,
                            'zone': obj.zone,
                            'battlefield_row': obj.battlefield_row,
                            'owner_seat': obj.owner.seat_position,
                            'controller_seat': obj.controller.seat_position,
                            'is_token': False
                        }
                    zones_data[seat][obj.zone].append(obj_data)

            # Ações recentes
            recent_actions = []
            for action in GameAction.objects.filter(game=game).order_by('-timestamp')[:50]:
                recent_actions.append({
                    'id': str(action.id),
                    'action_type': action.action_type,
                    'display_text': action.display_text,
                    'turn_number': action.turn_number,
                    'phase': action.phase,
                    'timestamp': action.timestamp.isoformat()
                })

            # Commander damage
            cmd_damage = {}
            for cd in CommanderDamage.objects.filter(game=game):
                key = f"{cd.target_player.seat_position}_{cd.source_player.seat_position}"
                cmd_damage[key] = cd.damage

            # Encontrar jogador ativo
            active_player = None
            for p in players:
                if p['seat_position'] == game.active_player_seat:
                    active_player = p['nickname']
                    break

            return {
                'game_id': str(game.id),
                'status': game.status,
                'turn_number': game.turn_number,
                'current_phase': game.current_phase,
                'phase_display': game.get_current_phase_display(),
                'active_player_seat': game.active_player_seat,
                'active_player_name': active_player,
                'players': players,
                'zones_data': zones_data,
                'recent_actions': recent_actions,
                'cmd_damage': cmd_damage,
                'winner_id': str(game.winner.id) if game.winner else None
            }
        except Game.DoesNotExist:
            return None

    @database_sync_to_async
    def get_game_player(self):
        from game.models import GamePlayer
        from accounts.models import PlayerProfile
        if not self.player_id:
            return None
        try:
            player = PlayerProfile.objects.get(id=self.player_id)
            return GamePlayer.objects.get(game_id=self.game_id, player=player)
        except:
            return None

    @database_sync_to_async
    def execute_game_action(self, action, data):
        from game.models import Game, GamePlayer, GameObject, GameAction, CommanderDamage
        from accounts.models import PlayerProfile
        import random

        if not self.player_id:
            return {'success': False, 'error': 'Not authenticated'}

        try:
            game = Game.objects.get(id=self.game_id)
            player = PlayerProfile.objects.get(id=self.player_id)
            game_player = GamePlayer.objects.get(game=game, player=player)
        except Exception as e:
            return {'success': False, 'error': f'Game or player not found: {e}'}

        try:
            if action == 'move_card':
                obj_id = data.get('object_id')
                new_zone = data.get('zone')
                target_seat = data.get('target_seat')  # For moving to another player
                row = data.get('row')  # For battlefield organization

                obj = GameObject.objects.filter(id=obj_id, game=game).first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                old_zone = obj.zone
                old_controller = obj.controller

                # Get card/token name for logging
                card_name = obj.token_name if obj.is_token else (obj.card.name if obj.card else 'Unknown')

                # Tokens cease to exist when they leave the battlefield (per MTG rules)
                # Exception: tokens can move to exile or return to battlefield
                if obj.is_token and old_zone == 'battlefield' and new_zone not in ['battlefield', 'exile']:
                    # Token goes to graveyard/hand/library = ceases to exist
                    obj.delete()

                    GameAction.objects.create(
                        game=game,
                        action_type='zone_change',
                        player=game_player,
                        data={
                            'card': card_name,
                            'from': old_zone,
                            'to': new_zone,
                            'is_token': True
                        },
                        display_text=f"{game_player.player.nickname} destruiu token {card_name}",
                        turn_number=game.turn_number,
                        phase=game.current_phase
                    )
                    return {'success': True, 'token_destroyed': True}

                obj.zone = new_zone
                obj.is_tapped = False

                # Handle moving to another player's battlefield
                if target_seat is not None:
                    new_controller = GamePlayer.objects.filter(game=game, seat_position=target_seat).first()
                    if new_controller:
                        obj.controller = new_controller

                # Handle battlefield row
                if new_zone == 'battlefield' and row:
                    obj.battlefield_row = row
                elif new_zone == 'battlefield' and not obj.battlefield_row:
                    # Auto-detect row based on card/token type
                    if obj.is_token:
                        type_line = (obj.token_type or '').lower()
                    else:
                        type_line = (obj.card.type_line or '').lower() if obj.card else ''
                    if 'creature' in type_line:
                        obj.battlefield_row = 'creatures'
                    elif 'land' in type_line:
                        obj.battlefield_row = 'lands'
                    else:
                        obj.battlefield_row = 'enchantments'

                obj.save()

                # Build display text
                if target_seat is not None and obj.controller != old_controller:
                    display_text = f"{game_player.player.nickname} moveu {card_name} para o campo de {obj.controller.player.nickname}"
                else:
                    display_text = f"{game_player.player.nickname} moveu {card_name} de {old_zone} para {new_zone}"

                GameAction.objects.create(
                    game=game,
                    action_type='zone_change',
                    player=game_player,
                    data={
                        'card': card_name,
                        'from': old_zone,
                        'to': new_zone,
                        'target_seat': target_seat,
                        'row': row
                    },
                    display_text=display_text,
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True}

            elif action == 'tap_card':
                obj_id = data.get('object_id')
                obj = GameObject.objects.filter(id=obj_id, game=game, zone='battlefield').first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                obj.is_tapped = not obj.is_tapped
                obj.save()

                card_name = obj.token_name if obj.is_token else (obj.card.name if obj.card else 'Unknown')
                action_text = 'virou' if obj.is_tapped else 'desvirou'
                GameAction.objects.create(
                    game=game,
                    action_type='tap' if obj.is_tapped else 'untap',
                    player=game_player,
                    data={'card': card_name},
                    display_text=f"{game_player.player.nickname} {action_text} {card_name}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True, 'is_tapped': obj.is_tapped}

            elif action == 'change_life':
                target_seat = data.get('target_seat')
                delta = data.get('delta', 0)
                target = GamePlayer.objects.filter(game=game, seat_position=target_seat).first()
                if not target:
                    return {'success': False, 'error': 'Player not found'}

                old_life = target.life
                target.life += delta
                target.save()

                if target.life <= 0:
                    target.is_alive = False
                    target.has_lost = True
                    target.save()
                    self._check_winner(game)

                GameAction.objects.create(
                    game=game,
                    action_type='life_change',
                    player=game_player,
                    data={'target': target.player.nickname, 'old': old_life, 'new': target.life},
                    display_text=f"{target.player.nickname}: {old_life} -> {target.life}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True, 'new_life': target.life}

            elif action == 'add_counter':
                obj_id = data.get('object_id')
                counter_type = data.get('counter_type', '+1/+1')
                obj = GameObject.objects.filter(id=obj_id, game=game).first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                counters = obj.counters or {}
                counters[counter_type] = counters.get(counter_type, 0) + 1
                obj.counters = counters
                obj.save()

                card_name = obj.token_name if obj.is_token else (obj.card.name if obj.card else 'Unknown')
                GameAction.objects.create(
                    game=game,
                    action_type='counter_change',
                    player=game_player,
                    data={'card': card_name, 'counter': counter_type, 'add': True},
                    display_text=f"{game_player.player.nickname} adicionou {counter_type} em {card_name}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True, 'counters': counters}

            elif action == 'remove_counter':
                obj_id = data.get('object_id')
                counter_type = data.get('counter_type', '+1/+1')
                obj = GameObject.objects.filter(id=obj_id, game=game).first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                counters = obj.counters or {}
                counters[counter_type] = max(0, counters.get(counter_type, 0) - 1)
                obj.counters = counters
                obj.save()

                card_name = obj.token_name if obj.is_token else (obj.card.name if obj.card else 'Unknown')
                GameAction.objects.create(
                    game=game,
                    action_type='counter_change',
                    player=game_player,
                    data={'card': card_name, 'counter': counter_type, 'add': False},
                    display_text=f"{game_player.player.nickname} removeu {counter_type} de {card_name}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True, 'counters': counters}

            elif action == 'next_phase':
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
                return {'success': True, 'phase': game.current_phase}

            elif action == 'next_turn':
                alive_players = list(game.players.filter(is_alive=True).order_by('seat_position'))
                if not alive_players:
                    return {'success': False, 'error': 'No alive players'}

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
                active = alive_players[next_idx]
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
                return {'success': True, 'turn': game.turn_number, 'active_seat': game.active_player_seat}

            elif action == 'draw_card':
                library = GameObject.objects.filter(
                    game=game,
                    owner=game_player,
                    zone='library'
                ).order_by('zone_position').first()

                if not library:
                    game_player.is_alive = False
                    game_player.has_lost = True
                    game_player.save()
                    self._check_winner(game)
                    return {'success': False, 'error': 'No cards in library', 'lost': True}

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
                return {'success': True, 'card_id': str(library.id)}

            elif action == 'shuffle_library':
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
                return {'success': True}

            elif action == 'concede':
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

                self._check_winner(game)
                return {'success': True}

            # ========== NEW LIBRARY MANIPULATION ACTIONS ==========

            elif action == 'scry':
                # Look at top X cards - private action (only sender sees)
                count = min(data.get('count', 1), 10)  # Max 10 cards
                library_cards = list(GameObject.objects.filter(
                    game=game,
                    owner=game_player,
                    zone='library'
                ).select_related('card').order_by('zone_position')[:count])

                cards_data = [{
                    'id': str(c.id),
                    'name': c.card.name,
                    'type_line': c.card.type_line or '',
                    'image_normal': c.card.image_normal or '',
                    'image_small': c.card.image_small or ''
                } for c in library_cards]

                GameAction.objects.create(
                    game=game,
                    action_type='scry',
                    player=game_player,
                    data={'count': count},
                    display_text=f"{game_player.player.nickname} fez videncia {count}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )

                return {'success': True, 'cards': cards_data, 'private': True}

            elif action == 'look_top':
                # Look at top X cards without logging (internal use)
                count = min(data.get('count', 1), 10)
                library_cards = list(GameObject.objects.filter(
                    game=game,
                    owner=game_player,
                    zone='library'
                ).select_related('card').order_by('zone_position')[:count])

                cards_data = [{
                    'id': str(c.id),
                    'name': c.card.name,
                    'type_line': c.card.type_line or '',
                    'image_normal': c.card.image_normal or '',
                    'image_small': c.card.image_small or ''
                } for c in library_cards]

                return {'success': True, 'cards': cards_data, 'private': True}

            elif action == 'put_top':
                # Put a card on top of library
                obj_id = data.get('object_id')
                obj = GameObject.objects.filter(id=obj_id, game=game).first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                # Tokens can't go to library - they cease to exist
                if obj.is_token:
                    card_name = obj.token_name
                    obj.delete()
                    GameAction.objects.create(
                        game=game,
                        action_type='zone_change',
                        player=game_player,
                        data={'card': card_name, 'is_token': True},
                        display_text=f"{game_player.player.nickname} destruiu token {card_name}",
                        turn_number=game.turn_number,
                        phase=game.current_phase
                    )
                    return {'success': True, 'token_destroyed': True}

                old_zone = obj.zone
                card_name = obj.card.name if obj.card else 'Unknown'

                # Shift all library cards down by 1 to make room at position 0
                library_cards = GameObject.objects.filter(
                    game=game,
                    owner=obj.owner,
                    zone='library'
                ).exclude(id=obj_id).order_by('zone_position')

                for i, card in enumerate(library_cards):
                    card.zone_position = i + 1
                    card.save()

                # Place the card at position 0 (top)
                obj.zone = 'library'
                obj.zone_position = 0
                obj.is_tapped = False
                obj.save()

                GameAction.objects.create(
                    game=game,
                    action_type='put_top',
                    player=game_player,
                    data={'card': card_name, 'from': old_zone},
                    display_text=f"{game_player.player.nickname} colocou {card_name} no topo da biblioteca",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True}

            elif action == 'put_bottom':
                # Put a card on bottom of library
                obj_id = data.get('object_id')
                obj = GameObject.objects.filter(id=obj_id, game=game).first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                # Tokens can't go to library - they cease to exist
                if obj.is_token:
                    card_name = obj.token_name
                    obj.delete()
                    GameAction.objects.create(
                        game=game,
                        action_type='zone_change',
                        player=game_player,
                        data={'card': card_name, 'is_token': True},
                        display_text=f"{game_player.player.nickname} destruiu token {card_name}",
                        turn_number=game.turn_number,
                        phase=game.current_phase
                    )
                    return {'success': True, 'token_destroyed': True}

                old_zone = obj.zone
                card_name = obj.card.name if obj.card else 'Unknown'
                # Get maximum position (bottom of library)
                max_pos = GameObject.objects.filter(
                    game=game,
                    owner=obj.owner,
                    zone='library'
                ).order_by('-zone_position').values_list('zone_position', flat=True).first()

                obj.zone = 'library'
                obj.zone_position = (max_pos or 0) + 1
                obj.is_tapped = False
                obj.save()

                GameAction.objects.create(
                    game=game,
                    action_type='put_bottom',
                    player=game_player,
                    data={'card': card_name, 'from': old_zone},
                    display_text=f"{game_player.player.nickname} colocou {card_name} no fundo da biblioteca",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True}

            elif action == 'reveal_card':
                # Reveal a card to all players
                obj_id = data.get('object_id')
                obj = GameObject.objects.filter(id=obj_id, game=game).select_related('card').first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                obj.is_revealed = True
                obj.save()

                card_name = obj.token_name if obj.is_token else (obj.card.name if obj.card else 'Unknown')
                card_image = '' if obj.is_token else (obj.card.image_normal or '' if obj.card else '')

                GameAction.objects.create(
                    game=game,
                    action_type='reveal',
                    player=game_player,
                    data={'card': card_name, 'zone': obj.zone},
                    display_text=f"{game_player.player.nickname} revelou {card_name}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )

                return {
                    'success': True,
                    'broadcast_reveal': True,
                    'revealed_card': {
                        'id': str(obj.id),
                        'name': card_name,
                        'image_normal': card_image,
                        'player': game_player.player.nickname,
                        'is_token': obj.is_token
                    }
                }

            elif action == 'shuffle_into':
                # Put a card into library and shuffle
                obj_id = data.get('object_id')
                obj = GameObject.objects.filter(id=obj_id, game=game).first()
                if not obj:
                    return {'success': False, 'error': 'Object not found'}

                # Tokens can't go to library - they cease to exist
                if obj.is_token:
                    card_name = obj.token_name
                    obj.delete()
                    GameAction.objects.create(
                        game=game,
                        action_type='zone_change',
                        player=game_player,
                        data={'card': card_name, 'is_token': True},
                        display_text=f"{game_player.player.nickname} destruiu token {card_name}",
                        turn_number=game.turn_number,
                        phase=game.current_phase
                    )
                    return {'success': True, 'token_destroyed': True}

                old_zone = obj.zone
                card_name = obj.card.name if obj.card else 'Unknown'

                # Move to library
                obj.zone = 'library'
                obj.is_tapped = False
                obj.save()

                # Shuffle all library cards
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
                    action_type='shuffle_into',
                    player=game_player,
                    data={'card': card_name, 'from': old_zone},
                    display_text=f"{game_player.player.nickname} embaralhou {card_name} na biblioteca",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True}

            elif action == 'reorder_scry':
                # Reorder cards after scrying - receives list of {id, position: 'top'|'bottom'}
                order = data.get('order', [])

                if not order:
                    return {'success': True, 'private': True}

                # Separate cards going to top vs bottom
                top_cards = [item for item in order if item.get('position') != 'bottom']
                bottom_cards = [item for item in order if item.get('position') == 'bottom']

                # Get all library cards ordered by position
                library_cards = list(GameObject.objects.filter(
                    game=game,
                    owner=game_player,
                    zone='library'
                ).order_by('zone_position'))

                # Get IDs of cards being reordered
                reorder_ids = {item['id'] for item in order}

                # Remove reordered cards from the middle of the library
                remaining_cards = [c for c in library_cards if str(c.id) not in reorder_ids]

                # Calculate new positions: top_cards first, then remaining, then bottom_cards
                new_position = 0

                # Place top cards first (in order they were added to top)
                for item in top_cards:
                    obj = GameObject.objects.filter(id=item['id'], game=game).first()
                    if obj:
                        obj.zone_position = new_position
                        obj.save()
                        new_position += 1

                # Place remaining library cards
                for card in remaining_cards:
                    card.zone_position = new_position
                    card.save()
                    new_position += 1

                # Place bottom cards last
                for item in bottom_cards:
                    obj = GameObject.objects.filter(id=item['id'], game=game).first()
                    if obj:
                        obj.zone_position = new_position
                        obj.save()
                        new_position += 1

                return {'success': True, 'private': True}

            elif action == 'set_battlefield_row':
                # Move a card to a specific battlefield row
                obj_id = data.get('object_id')
                row = data.get('row', 'other')
                obj = GameObject.objects.filter(id=obj_id, game=game, zone='battlefield').first()
                if not obj:
                    return {'success': False, 'error': 'Object not found on battlefield'}

                obj.battlefield_row = row
                obj.save()
                return {'success': True}

            elif action == 'go_to_phase':
                # Go directly to a specific phase
                target_phase = data.get('phase')
                valid_phases = ['untap', 'upkeep', 'draw', 'main1', 'combat_begin', 'combat_attackers',
                               'combat_blockers', 'combat_damage', 'combat_end', 'main2', 'end', 'cleanup']
                if target_phase not in valid_phases:
                    return {'success': False, 'error': 'Invalid phase'}

                old_phase = game.current_phase
                game.current_phase = target_phase
                game.save()

                GameAction.objects.create(
                    game=game,
                    action_type='phase_change',
                    player=game_player,
                    data={'from': old_phase, 'to': target_phase},
                    display_text=f"Fase: {game.get_current_phase_display()}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )
                return {'success': True, 'phase': target_phase}

            elif action == 'view_library':
                # View entire library - private action
                library_cards = list(GameObject.objects.filter(
                    game=game,
                    owner=game_player,
                    zone='library'
                ).select_related('card').order_by('zone_position'))

                cards_data = [{
                    'id': str(c.id),
                    'name': c.card.name,
                    'type_line': c.card.type_line or '',
                    'image_normal': c.card.image_normal or '',
                    'image_small': c.card.image_small or ''
                } for c in library_cards]

                GameAction.objects.create(
                    game=game,
                    action_type='look_top',
                    player=game_player,
                    data={'count': len(library_cards), 'full': True},
                    display_text=f"{game_player.player.nickname} olhou a biblioteca",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )

                return {'success': True, 'cards': cards_data, 'private': True}

            elif action == 'roll_dice':
                # Roll dice - broadcast to all players
                sides = data.get('sides', 20)
                result = data.get('result', 1)

                GameAction.objects.create(
                    game=game,
                    action_type='dice_roll',
                    player=game_player,
                    data={'sides': sides, 'result': result},
                    display_text=f"{game_player.player.nickname} rolou d{sides}: {result}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )

                return {
                    'success': True,
                    'broadcast_dice': True,
                    'player': game_player.player.nickname,
                    'sides': sides,
                    'result': result
                }

            elif action == 'set_starting_player':
                # Set the starting player
                seat = data.get('seat', 0)
                roll = data.get('roll', 0)

                game.active_player_seat = seat
                game.save()

                starting_player = GamePlayer.objects.filter(game=game, seat_position=seat).first()
                player_name = starting_player.player.nickname if starting_player else 'Desconhecido'

                GameAction.objects.create(
                    game=game,
                    action_type='starting_player',
                    player=game_player,
                    data={'seat': seat, 'roll': roll, 'player': player_name},
                    display_text=f"{player_name} foi escolhido para comecar (rolou {roll})",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )

                return {
                    'success': True,
                    'broadcast_starting': True,
                    'player': player_name,
                    'seat': seat,
                    'roll': roll
                }

            elif action == 'create_token':
                # Create token(s) on the battlefield
                token_name = data.get('token_name', 'Token')
                token_type = data.get('token_type', 'Creature Token')
                token_power = data.get('token_power', '')
                token_toughness = data.get('token_toughness', '')
                token_colors = data.get('token_colors', '')
                token_abilities = data.get('token_abilities', '')
                count = data.get('count', 1)
                is_tapped = data.get('is_tapped', False)
                row = data.get('row', 'creatures')

                created_tokens = []
                for _ in range(count):
                    token = GameObject.objects.create(
                        game=game,
                        card=None,
                        is_token=True,
                        token_name=token_name,
                        token_type=token_type,
                        token_power=token_power,
                        token_toughness=token_toughness,
                        token_colors=token_colors,
                        token_abilities=token_abilities,
                        owner=game_player,
                        controller=game_player,
                        zone='battlefield',
                        battlefield_row=row,
                        is_tapped=is_tapped
                    )
                    created_tokens.append(str(token.id))

                count_text = f"{count}x " if count > 1 else ""
                GameAction.objects.create(
                    game=game,
                    action_type='create_token',
                    player=game_player,
                    data={'token_name': token_name, 'count': count},
                    display_text=f"{game_player.player.nickname} criou {count_text}{token_name}",
                    turn_number=game.turn_number,
                    phase=game.current_phase
                )

                return {'success': True, 'token_ids': created_tokens}

            return {'success': False, 'error': 'Unknown action'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _check_winner(self, game):
        alive = game.players.filter(is_alive=True)
        if alive.count() == 1:
            winner = alive.first()
            winner.has_won = True
            winner.save()
            game.winner = winner
            game.status = 'finished'
            game.save()

    async def receive_json(self, content):
        action = content.get('action')

        if action == 'chat':
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'chat_message',
                    'message': content.get('message', ''),
                    'sender': content.get('sender', 'Anonymous')
                }
            )

        elif action == 'get_state':
            await self.send_game_state()

        # Arrow actions (visual only, no persistence needed)
        elif action == 'create_arrows':
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'arrows_broadcast',
                    'action': 'add_arrows',
                    'arrows': content.get('data', {}).get('arrows', []),
                    'sender_channel': self.channel_name
                }
            )

        elif action == 'remove_arrow':
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'arrows_broadcast',
                    'action': 'remove_arrow',
                    'arrow': content.get('data', {}).get('arrow', {}),
                    'sender_channel': self.channel_name
                }
            )

        elif action == 'remove_arrows':
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'arrows_broadcast',
                    'action': 'remove_from_card',
                    'sourceCardId': content.get('data', {}).get('sourceCardId'),
                    'sender_channel': self.channel_name
                }
            )

        elif action == 'clear_arrows':
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'arrows_broadcast',
                    'action': 'clear_all',
                    'sender_channel': self.channel_name
                }
            )

        # Card stacking (visual organization, broadcast to all)
        elif action == 'sync_stacks':
            seat = content.get('data', {}).get('seat')
            stacks = content.get('data', {}).get('stacks', [])
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'stacks_broadcast',
                    'seat': seat,
                    'stacks': stacks
                }
            )

        elif action in ['move_card', 'tap_card', 'change_life', 'add_counter', 'remove_counter',
                        'next_phase', 'next_turn', 'draw_card', 'shuffle_library', 'concede',
                        'scry', 'look_top', 'put_top', 'put_bottom', 'reveal_card',
                        'shuffle_into', 'reorder_scry', 'set_battlefield_row',
                        'go_to_phase', 'view_library', 'roll_dice', 'set_starting_player',
                        'create_token']:
            result = await self.execute_game_action(action, content.get('data', {}))

            # Send action result to the sender
            await self.send_json({
                'type': 'action_result',
                'action': action,
                'result': result
            })

            if result.get('success'):
                # Check if it's a private action (only sender sees)
                if result.get('private'):
                    # Send private data only to sender
                    await self.send_json({
                        'type': 'private_action',
                        'action': action,
                        'data': result
                    })
                # Check if we need to broadcast a reveal
                elif result.get('broadcast_reveal'):
                    await self.channel_layer.group_send(
                        self.group_name,
                        {
                            'type': 'card_revealed',
                            'card': result['revealed_card']
                        }
                    )
                    await self.broadcast_game_state()
                # Check if we need to broadcast a dice roll
                elif result.get('broadcast_dice'):
                    await self.channel_layer.group_send(
                        self.group_name,
                        {
                            'type': 'dice_rolled',
                            'player': result['player'],
                            'sides': result['sides'],
                            'result': result['result']
                        }
                    )
                # Check if we need to broadcast starting player
                elif result.get('broadcast_starting'):
                    await self.channel_layer.group_send(
                        self.group_name,
                        {
                            'type': 'starting_player_selected',
                            'player': result['player'],
                            'seat': result['seat'],
                            'roll': result['roll']
                        }
                    )
                    await self.broadcast_game_state()
                else:
                    # Normal broadcast to all players
                    await self.broadcast_game_state()

    async def send_game_state(self):
        state = await self.get_game_state()
        if state:
            await self.send_json({
                'type': 'game_state',
                'state': state
            })

    async def broadcast_game_state(self):
        state = await self.get_game_state()
        if state:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'game_state_update',
                    'state': state
                }
            )

    async def chat_message(self, event):
        await self.send_json({
            'type': 'chat',
            'message': event['message'],
            'sender': event['sender']
        })

    async def game_state_update(self, event):
        await self.send_json({
            'type': 'game_state',
            'state': event['state']
        })

    async def card_revealed(self, event):
        """Broadcast when a card is revealed to all players"""
        await self.send_json({
            'type': 'reveal',
            'card': event['card']
        })

    async def dice_rolled(self, event):
        """Broadcast when a player rolls dice"""
        await self.send_json({
            'type': 'dice_roll',
            'player': event['player'],
            'sides': event['sides'],
            'result': event['result']
        })

    async def starting_player_selected(self, event):
        """Broadcast when starting player is determined"""
        await self.send_json({
            'type': 'starting_player_set',
            'player': event['player'],
            'seat': event['seat'],
            'roll': event['roll']
        })

    async def arrows_broadcast(self, event):
        """Broadcast arrow updates to all players except sender"""
        # Don't send back to the sender (they already updated locally)
        if event.get('sender_channel') == self.channel_name:
            return

        data = {'action': event['action']}

        if event['action'] == 'add_arrows':
            data['arrows'] = event.get('arrows', [])
        elif event['action'] == 'remove_arrow':
            data['arrow'] = event.get('arrow', {})
        elif event['action'] == 'remove_from_card':
            data['sourceCardId'] = event.get('sourceCardId')
        # clear_all doesn't need extra data

        await self.send_json({
            'type': 'arrows_update',
            **data
        })

    async def stacks_broadcast(self, event):
        """Broadcast card stack updates to all players"""
        await self.send_json({
            'type': 'stacks_update',
            'seat': event['seat'],
            'stacks': event['stacks']
        })
