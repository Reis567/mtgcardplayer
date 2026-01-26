from django.urls import path
from . import views

urlpatterns = [
    path('', views.LobbyListView.as_view(), name='lobby_list'),
    path('create/', views.LobbyCreateView.as_view(), name='lobby_create'),
    path('<uuid:lobby_id>/', views.LobbyDetailView.as_view(), name='lobby_detail'),
]
