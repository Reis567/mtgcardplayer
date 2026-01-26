from django.db import models
from accounts.models import PlayerProfile
from decks.models import Deck
import uuid


class Lobby(models.Model):
    """Sala de espera para partida"""
    STATUS_CHOICES = [
        ('waiting', 'Aguardando Jogadores'),
        ('ready', 'Pronto para Iniciar'),
        ('in_game', 'Em Jogo'),
        ('finished', 'Finalizado'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, default='Partida Commander')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')

    min_players = models.PositiveSmallIntegerField(default=2)
    max_players = models.PositiveSmallIntegerField(default=4)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)

    game = models.OneToOneField(
        'game.Game',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lobby'
    )

    class Meta:
        verbose_name_plural = 'Lobbies'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def player_count(self):
        return self.players.count()

    def ready_count(self):
        return self.players.filter(is_ready=True).count()

    def can_start(self):
        ready = self.ready_count()
        total = self.player_count()
        return total >= self.min_players and ready == total


class LobbyPlayer(models.Model):
    """Jogador no lobby"""
    lobby = models.ForeignKey(Lobby, on_delete=models.CASCADE, related_name='players')
    player = models.ForeignKey(PlayerProfile, on_delete=models.CASCADE)
    deck = models.ForeignKey(Deck, on_delete=models.SET_NULL, null=True, blank=True)

    is_ready = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    seat_position = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ['lobby', 'player']
        ordering = ['joined_at']

    def __str__(self):
        return f"{self.player.nickname} @ {self.lobby.name}"
