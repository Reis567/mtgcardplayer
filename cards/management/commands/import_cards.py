import json
import requests
from django.core.management.base import BaseCommand
from cards.models import Card


class Command(BaseCommand):
    help = 'Importa cartas do Scryfall Bulk Data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Tamanho do batch para bulk_create (default: 1000)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Limpa todas as cartas antes de importar'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']

        if options['clear']:
            self.stdout.write('Limpando cartas existentes...')
            Card.objects.all().delete()

        self.stdout.write('Buscando URL do bulk data...')

        headers = {
            'User-Agent': 'MTGCardsApp/1.0',
            'Accept': 'application/json'
        }

        response = requests.get(
            'https://api.scryfall.com/bulk-data',
            headers=headers
        )
        response.raise_for_status()
        bulk_data = response.json()

        download_url = None
        for item in bulk_data['data']:
            if item['type'] == 'default_cards':
                download_url = item['download_uri']
                break

        if not download_url:
            self.stderr.write(self.style.ERROR('Nao foi possivel encontrar o bulk data'))
            return

        self.stdout.write(f'Baixando bulk data de: {download_url}')
        self.stdout.write('Isso pode demorar alguns minutos...')

        response = requests.get(download_url, headers=headers, stream=True)
        response.raise_for_status()

        self.stdout.write('Processando cartas...')

        cards_data = response.json()
        total_cards = len(cards_data)
        self.stdout.write(f'Total de cartas encontradas: {total_cards}')

        cards_to_create = []
        cards_to_update = []
        existing_ids = set(Card.objects.values_list('scryfall_id', flat=True))

        for i, card_data in enumerate(cards_data):
            if (i + 1) % 10000 == 0:
                self.stdout.write(f'Processando carta {i + 1}/{total_cards}...')

            if card_data.get('layout') in ['art_series', 'token', 'double_faced_token', 'emblem']:
                continue

            image_uris = card_data.get('image_uris', {})
            if not image_uris and 'card_faces' in card_data:
                image_uris = card_data['card_faces'][0].get('image_uris', {})

            card = Card(
                scryfall_id=card_data['id'],
                name=card_data['name'],
                mana_cost=card_data.get('mana_cost', ''),
                cmc=card_data.get('cmc', 0),
                type_line=card_data.get('type_line', ''),
                oracle_text=card_data.get('oracle_text', ''),
                colors=','.join(card_data.get('colors', [])),
                color_identity=','.join(card_data.get('color_identity', [])),
                set_code=card_data.get('set', ''),
                set_name=card_data.get('set_name', ''),
                rarity=card_data.get('rarity', 'common'),
                image_small=image_uris.get('small', ''),
                image_normal=image_uris.get('normal', ''),
                image_large=image_uris.get('large', ''),
                power=card_data.get('power'),
                toughness=card_data.get('toughness'),
                loyalty=card_data.get('loyalty'),
            )

            from uuid import UUID
            card_uuid = UUID(card_data['id'])

            if card_uuid in existing_ids:
                cards_to_update.append(card)
            else:
                cards_to_create.append(card)

            if len(cards_to_create) >= batch_size:
                Card.objects.bulk_create(cards_to_create, ignore_conflicts=True)
                self.stdout.write(f'Inseridas {len(cards_to_create)} cartas...')
                cards_to_create = []

        if cards_to_create:
            Card.objects.bulk_create(cards_to_create, ignore_conflicts=True)
            self.stdout.write(f'Inseridas {len(cards_to_create)} cartas...')

        total_in_db = Card.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f'Importacao concluida! Total de cartas no banco: {total_in_db}')
        )
