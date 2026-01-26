from django.views.generic import ListView
from django.db.models import Q
from .models import Card


class CardListView(ListView):
    model = Card
    template_name = 'cards/card_list.html'
    context_object_name = 'cards'
    paginate_by = 50

    def get_queryset(self):
        queryset = Card.objects.all()

        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(oracle_text__icontains=search) |
                Q(type_line__icontains=search)
            )

        color = self.request.GET.get('color', '').strip().upper()
        if color:
            queryset = queryset.filter(colors__icontains=color)

        set_code = self.request.GET.get('set', '').strip().lower()
        if set_code:
            queryset = queryset.filter(set_code=set_code)

        rarity = self.request.GET.get('rarity', '').strip().lower()
        if rarity:
            queryset = queryset.filter(rarity=rarity)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['color'] = self.request.GET.get('color', '')
        context['set'] = self.request.GET.get('set', '')
        context['rarity'] = self.request.GET.get('rarity', '')
        context['total_cards'] = Card.objects.count()
        return context
