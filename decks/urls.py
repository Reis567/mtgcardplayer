from django.urls import path
from . import views

urlpatterns = [
    path('', views.DeckListView.as_view(), name='deck_list'),
    path('import/', views.DeckImportView.as_view(), name='deck_import'),
    path('parse/', views.ParseDecklistView.as_view(), name='deck_parse'),
    path('<uuid:deck_id>/', views.DeckDetailView.as_view(), name='deck_detail'),
]
