from django.urls import path
from . import views

urlpatterns = [
    path('', views.DeckListView.as_view(), name='deck_list'),
    path('import/', views.DeckImportView.as_view(), name='deck_import'),
    path('parse/', views.ParseDecklistView.as_view(), name='deck_parse'),
    path('builder/', views.DeckBuilderView.as_view(), name='deck_builder'),
    path('analyzer/<uuid:deck_id>/', views.DeckAnalyzerView.as_view(), name='deck_analyzer'),
    path('mana-base/', views.ManaBaseGeneratorView.as_view(), name='mana_base_generator'),
    path('compare/', views.CardComparatorView.as_view(), name='card_comparator'),
    path('<uuid:deck_id>/', views.DeckDetailView.as_view(), name='deck_detail'),
]
