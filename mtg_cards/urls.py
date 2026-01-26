from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', lambda r: redirect('login'), name='home'),
    path('cards/', include('cards.urls')),
    path('', include('accounts.urls')),
    path('lobby/', include('lobby.urls')),
    path('decks/', include('decks.urls')),
    path('game/', include('game.urls')),
]
