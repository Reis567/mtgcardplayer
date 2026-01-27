from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('cards/', include('cards.urls')),
    path('lobby/', include('lobby.urls')),
    path('decks/', include('decks.urls')),
    path('game/', include('game.urls')),
    path('', include('accounts.urls')),
]
