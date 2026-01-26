from django.contrib import admin
from .models import Deck, DeckCard


class DeckCardInline(admin.TabularInline):
    model = DeckCard
    extra = 0
    raw_id_fields = ['card']


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'commander', 'color_identity', 'is_valid', 'updated_at']
    list_filter = ['is_valid', 'color_identity']
    search_fields = ['name', 'owner__nickname', 'commander__name']
    raw_id_fields = ['owner', 'commander', 'partner_commander']
    readonly_fields = ['id', 'created_at', 'updated_at']
    inlines = [DeckCardInline]
