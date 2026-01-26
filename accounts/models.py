from django.db import models
import uuid


class PlayerProfile(models.Model):
    """Perfil do jogador apos login global"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    nickname = models.CharField(max_length=30)
    avatar_url = models.URLField(blank=True, null=True)
    avatar_color = models.CharField(max_length=7, default='#e94560')
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    is_online = models.BooleanField(default=False)

    games_played = models.PositiveIntegerField(default=0)
    games_won = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-last_seen']

    def __str__(self):
        return self.nickname
