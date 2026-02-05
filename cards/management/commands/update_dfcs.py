import requests
import time
from django.core.management.base import BaseCommand
from cards.models import Card


class Command(BaseCommand):
    help = 'Atualiza cartas de duas faces (DFCs) com dados do Scryfall'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Limitar numero de cartas a atualizar (0 = todas)'
        )

    def handle(self, *args, **options):
        limit = options['limit']

        # Buscar cartas que tem '//' no nome (indicando DFC)
        dfcs = Card.objects.filter(name__contains=' // ')
        total = dfcs.count()

        if limit > 0:
            dfcs = dfcs[:limit]

        self.stdout.write(f'Encontradas {total} cartas DFC. Atualizando {dfcs.count()}...')

        headers = {
            'User-Agent': 'MTGCardsApp/1.0',
            'Accept': 'application/json'
        }

        updated = 0
        errors = 0

        for card in dfcs:
            try:
                # Buscar dados atualizados do Scryfall
                url = f'https://api.scryfall.com/cards/{card.scryfall_id}'
                response = requests.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()

                    # Atualizar layout
                    card.layout = data.get('layout', 'normal')

                    # Processar faces
                    card_faces = data.get('card_faces', [])

                    if len(card_faces) >= 2:
                        front = card_faces[0]
                        back = card_faces[1]

                        # Imagens da face frontal (se nao tinha)
                        front_images = front.get('image_uris', {})
                        if front_images:
                            card.image_small = front_images.get('small') or card.image_small
                            card.image_normal = front_images.get('normal') or card.image_normal
                            card.image_large = front_images.get('large') or card.image_large

                        # Dados da face frontal
                        card.mana_cost = card.mana_cost or front.get('mana_cost', '')
                        card.oracle_text = card.oracle_text or front.get('oracle_text', '')
                        card.type_line = card.type_line or front.get('type_line', '')
                        card.power = card.power or front.get('power')
                        card.toughness = card.toughness or front.get('toughness')
                        card.loyalty = card.loyalty or front.get('loyalty')

                        # Dados da face traseira
                        back_images = back.get('image_uris', {})
                        card.back_face_name = back.get('name')
                        card.back_face_mana_cost = back.get('mana_cost')
                        card.back_face_type_line = back.get('type_line')
                        card.back_face_oracle_text = back.get('oracle_text')
                        card.back_face_power = back.get('power')
                        card.back_face_toughness = back.get('toughness')
                        card.back_face_loyalty = back.get('loyalty')
                        card.back_face_image_small = back_images.get('small')
                        card.back_face_image_normal = back_images.get('normal')
                        card.back_face_image_large = back_images.get('large')

                        card.save()
                        updated += 1

                        if updated % 50 == 0:
                            self.stdout.write(f'  Atualizadas {updated} cartas...')

                elif response.status_code == 404:
                    self.stdout.write(self.style.WARNING(f'  Carta nao encontrada: {card.name}'))
                    errors += 1
                else:
                    self.stdout.write(self.style.WARNING(f'  Erro {response.status_code} para {card.name}'))
                    errors += 1

                # Rate limiting - Scryfall pede 50-100ms entre requests
                time.sleep(0.1)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Erro ao atualizar {card.name}: {e}'))
                errors += 1

        self.stdout.write(self.style.SUCCESS(
            f'Concluido! Atualizadas: {updated}, Erros: {errors}'
        ))
