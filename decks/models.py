from django.db import models
from accounts.models import PlayerProfile
from cards.models import Card
import uuid


class Deck(models.Model):
    """Deck de Commander"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(PlayerProfile, on_delete=models.CASCADE, related_name='decks')
    name = models.CharField(max_length=100)

    commander = models.ForeignKey(
        Card,
        on_delete=models.PROTECT,
        related_name='decks_as_commander'
    )
    partner_commander = models.ForeignKey(
        Card,
        on_delete=models.PROTECT,
        related_name='decks_as_partner',
        null=True,
        blank=True
    )

    color_identity = models.CharField(max_length=10, blank=True)
    raw_decklist = models.TextField(blank=True)
    is_valid = models.BooleanField(default=False)
    validation_errors = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} ({self.owner.nickname})"

    def card_count(self):
        """Total de cartas no deck (incluindo comandante)"""
        count = 1  # Comandante
        if self.partner_commander:
            count += 1
        count += sum(dc.quantity for dc in self.cards.all())
        return count


class DeckCard(models.Model):
    """Carta no deck (nao-comandante)"""
    deck = models.ForeignKey(Deck, on_delete=models.CASCADE, related_name='cards')
    card = models.ForeignKey(Card, on_delete=models.PROTECT)
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = ['deck', 'card']

    def __str__(self):
        return f"{self.quantity}x {self.card.name}"
