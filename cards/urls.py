from django.urls import path
from .views import (
    CardListView, CardCatalogView, CardDetailView,
    CardAutocompleteView, RandomCardView
)

urlpatterns = [
    # Catalogo principal (nova pagina com filtros avancados)
    path('', CardCatalogView.as_view(), name='card_catalog'),

    # Listagem simples (legado)
    path('list/', CardListView.as_view(), name='card_list'),

    # Detalhes do card
    path('card/<int:card_id>/', CardDetailView.as_view(), name='card_detail'),
    path('card/name/<str:card_name>/', CardDetailView.as_view(), name='card_detail_by_name'),

    # API endpoints
    path('api/autocomplete/', CardAutocompleteView.as_view(), name='card_autocomplete'),
    path('random/', RandomCardView.as_view(), name='card_random'),
]
