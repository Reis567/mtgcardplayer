from django.contrib import admin
from .models import Card


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['name', 'set_code', 'rarity', 'mana_cost', 'type_line']
    list_filter = ['rarity', 'set_code', 'colors']
    search_fields = ['name', 'oracle_text', 'type_line']
    readonly_fields = ['scryfall_id']
