from django.contrib import admin
from .models import PlayerProfile


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ['nickname', 'avatar_color', 'is_online', 'games_played', 'games_won', 'last_seen']
    list_filter = ['is_online']
    search_fields = ['nickname', 'session_key']
    readonly_fields = ['id', 'session_key', 'created_at', 'last_seen']
