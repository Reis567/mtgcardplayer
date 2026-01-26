from django.db import models
from accounts.models import PlayerProfile
from cards.models import Card
from decks.models import Deck
import uuid


class Game(models.Model):
    """Partida de Commander"""
    STATUS_CHOICES = [
        ('setup', 'Configurando'),
        ('mulligans', 'Mulligans'),
        ('active', 'Em Andamento'),
        ('paused', 'Pausado'),
        ('finished', 'Finalizado'),
    ]

    PHASE_CHOICES = [
        ('untap', 'Desvirar'),
        ('upkeep', 'Manutencao'),
        ('draw', 'Compra'),
        ('main1', 'Primeira Fase Principal'),
        ('combat_begin', 'Inicio do Combate'),
        ('combat_attackers', 'Declarar Atacantes'),
        ('combat_blockers', 'Declarar Bloqueadores'),
        ('combat_damage', 'Dano de Combate'),
        ('combat_end', 'Fim do Combate'),
        ('main2', 'Segunda Fase Principal'),
        ('end', 'Fase Final'),
        ('cleanup', 'Limpeza'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='setup')

    turn_number = models.PositiveIntegerField(default=0)
    active_player_seat = models.PositiveSmallIntegerField(default=0)
    current_phase = models.CharField(max_length=20, choices=PHASE_CHOICES, default='untap')

    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    winner = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='games_won'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Game {str(self.id)[:8]} - Turn {self.turn_number}"

    def get_active_player(self):
        return self.players.filter(seat_position=self.active_player_seat).first()


class GamePlayer(models.Model):
    """Jogador em uma partida"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='players')
    player = models.ForeignKey(PlayerProfile, on_delete=models.CASCADE)
    deck = models.ForeignKey(Deck, on_delete=models.PROTECT)
    seat_position = models.PositiveSmallIntegerField()

    life = models.IntegerField(default=40)
    poison_counters = models.PositiveSmallIntegerField(default=0)

    is_alive = models.BooleanField(default=True)
    has_lost = models.BooleanField(default=False)
    has_won = models.BooleanField(default=False)

    lands_played_this_turn = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ['game', 'seat_position']
        ordering = ['seat_position']

    def __str__(self):
        return f"{self.player.nickname} (Seat {self.seat_position})"


class CommanderDamage(models.Model):
    """Rastreamento de dano de comandante (21 = derrota)"""
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='commander_damage')
    target_player = models.ForeignKey(
        GamePlayer,
        on_delete=models.CASCADE,
        related_name='commander_damage_received'
    )
    source_player = models.ForeignKey(
        GamePlayer,
        on_delete=models.CASCADE,
        related_name='commander_damage_dealt'
    )
    commander_card = models.ForeignKey(Card, on_delete=models.PROTECT)
    damage = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ['game', 'target_player', 'source_player', 'commander_card']

    def __str__(self):
        return f"{self.source_player} -> {self.target_player}: {self.damage}"


class GameObject(models.Model):
    """Objeto de jogo - representa uma carta em qualquer zona"""
    ZONE_CHOICES = [
        ('library', 'Biblioteca'),
        ('hand', 'Mao'),
        ('battlefield', 'Campo de Batalha'),
        ('graveyard', 'Cemiterio'),
        ('exile', 'Exilio'),
        ('command', 'Zona de Comando'),
        ('stack', 'Pilha'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='game_objects')
    card = models.ForeignKey(Card, on_delete=models.PROTECT)

    owner = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='owned_objects')
    controller = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='controlled_objects')

    zone = models.CharField(max_length=20, choices=ZONE_CHOICES)
    zone_position = models.PositiveIntegerField(default=0)

    is_tapped = models.BooleanField(default=False)
    is_face_down = models.BooleanField(default=False)

    counters = models.JSONField(default=dict, blank=True)
    damage_marked = models.PositiveIntegerField(default=0)

    is_commander = models.BooleanField(default=False)
    commander_cast_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['zone', 'zone_position']

    def __str__(self):
        return f"{self.card.name} ({self.zone}) - {self.controller.player.nickname}"


class GameAction(models.Model):
    """Log de acoes do jogo"""
    ACTION_TYPES = [
        ('game_start', 'Inicio do Jogo'),
        ('draw', 'Comprar'),
        ('play_land', 'Jogar Terreno'),
        ('cast_spell', 'Lancar Magia'),
        ('activate', 'Ativar Habilidade'),
        ('tap', 'Virar'),
        ('untap', 'Desvirar'),
        ('attack', 'Atacar'),
        ('block', 'Bloquear'),
        ('damage', 'Dano'),
        ('life_change', 'Mudanca de Vida'),
        ('zone_change', 'Mudanca de Zona'),
        ('counter_change', 'Mudanca de Marcadores'),
        ('phase_change', 'Mudanca de Fase'),
        ('turn_change', 'Mudanca de Turno'),
        ('concede', 'Conceder'),
        ('win', 'Vitoria'),
        ('lose', 'Derrota'),
        ('chat', 'Chat'),
        ('manual', 'Acao Manual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, null=True, blank=True)

    data = models.JSONField(default=dict, blank=True)
    display_text = models.TextField()

    timestamp = models.DateTimeField(auto_now_add=True)
    turn_number = models.PositiveIntegerField()
    phase = models.CharField(max_length=20)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"[T{self.turn_number}] {self.display_text}"
