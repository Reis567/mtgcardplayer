from django.contrib import admin
from .models import Lobby, LobbyPlayer


class LobbyPlayerInline(admin.TabularInline):
    model = LobbyPlayer
    extra = 0
    raw_id_fields = ['player', 'deck']


@admin.register(Lobby)
class LobbyAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'player_count', 'max_players', 'created_at']
    list_filter = ['status']
    search_fields = ['name']
    readonly_fields = ['id', 'created_at', 'started_at']
    inlines = [LobbyPlayerInline]
