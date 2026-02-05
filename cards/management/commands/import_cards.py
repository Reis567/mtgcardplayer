import json
import requests
import tempfile
import os
from django.core.management.base import BaseCommand
from cards.models import Card


class Command(BaseCommand):
    help = 'Importa cartas do Scryfall Bulk Data (otimizado para baixa memoria)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Tamanho do batch para bulk_create (default: 500)'
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

        # Baixar para arquivo temporario em vez de carregar tudo na memoria
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            response = requests.get(download_url, headers=headers, stream=True)
            response.raise_for_status()

            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    tmp_file.write(chunk)
                    downloaded += len(chunk)
                    if downloaded % (50 * 1024 * 1024) == 0:  # Log a cada 50MB
                        self.stdout.write(f'Baixado: {downloaded // (1024*1024)} MB...')

            self.stdout.write(f'Download completo: {downloaded // (1024*1024)} MB')

        try:
            self.stdout.write('Processando cartas (streaming)...')

            # Carregar IDs existentes para verificar duplicatas
            self.stdout.write('Carregando IDs existentes...')
            existing_ids = set(Card.objects.values_list('scryfall_id', flat=True))
            self.stdout.write(f'IDs existentes carregados: {len(existing_ids)}')

            cards_to_create = []
            processed = 0
            inserted = 0
            skipped = 0

            # Processar JSON incrementalmente usando ijson se disponivel, senao usar metodo alternativo
            try:
                import ijson
                self.stdout.write('Usando ijson para parsing incremental...')

                with open(tmp_path, 'rb') as f:
                    parser = ijson.items(f, 'item')

                    for card_data in parser:
                        result = self._process_card(card_data, existing_ids)
                        processed += 1

                        if result == 'skip':
                            skipped += 1
                            continue
                        elif result:
                            cards_to_create.append(result)

                        if len(cards_to_create) >= batch_size:
                            Card.objects.bulk_create(cards_to_create, ignore_conflicts=True)
                            inserted += len(cards_to_create)
                            self.stdout.write(f'Processadas {processed} cartas, inseridas {inserted}...')
                            cards_to_create = []

            except ImportError:
                self.stdout.write('ijson nao disponivel, usando metodo alternativo...')
                self.stdout.write('(Para melhor performance, instale: pip install ijson)')

                # Metodo alternativo: ler linha por linha (funciona com JSON array)
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    # Pular o '[' inicial
                    first_char = f.read(1)
                    while first_char and first_char in ' \n\r\t':
                        first_char = f.read(1)

                    if first_char != '[':
                        # Nao e um array, tentar carregar de outra forma
                        f.seek(0)
                        # Carregar em chunks menores
                        self._process_json_chunks(f, batch_size, existing_ids)
                        return

                    buffer = ''
                    depth = 0
                    in_string = False
                    escape = False

                    while True:
                        chunk = f.read(65536)  # 64KB por vez
                        if not chunk:
                            break

                        for char in chunk:
                            if escape:
                                buffer += char
                                escape = False
                                continue

                            if char == '\\' and in_string:
                                buffer += char
                                escape = True
                                continue

                            if char == '"':
                                in_string = not in_string
                                buffer += char
                                continue

                            if in_string:
                                buffer += char
                                continue

                            if char == '{':
                                depth += 1
                                buffer += char
                            elif char == '}':
                                depth -= 1
                                buffer += char
                                if depth == 0 and buffer.strip():
                                    # Objeto completo
                                    try:
                                        card_data = json.loads(buffer.strip())
                                        result = self._process_card(card_data, existing_ids)
                                        processed += 1

                                        if result == 'skip':
                                            skipped += 1
                                        elif result:
                                            cards_to_create.append(result)

                                        if len(cards_to_create) >= batch_size:
                                            Card.objects.bulk_create(cards_to_create, ignore_conflicts=True)
                                            inserted += len(cards_to_create)
                                            self.stdout.write(f'Processadas {processed} cartas, inseridas {inserted}...')
                                            cards_to_create = []
                                    except json.JSONDecodeError:
                                        pass
                                    buffer = ''
                            elif char in ',\n\r\t ':
                                if depth == 0:
                                    buffer = ''
                                else:
                                    buffer += char
                            else:
                                buffer += char

            # Inserir cartas restantes
            if cards_to_create:
                Card.objects.bulk_create(cards_to_create, ignore_conflicts=True)
                inserted += len(cards_to_create)

            total_in_db = Card.objects.count()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Importacao concluida! Processadas: {processed}, '
                    f'Inseridas: {inserted}, Puladas: {skipped}, '
                    f'Total no banco: {total_in_db}'
                )
            )

        finally:
            # Limpar arquivo temporario
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                self.stdout.write('Arquivo temporario removido.')

    def _process_card(self, card_data, existing_ids):
        """Processa uma carta e retorna o objeto Card ou None/skip"""
        # Pular tipos indesejados
        if card_data.get('layout') in ['art_series', 'token', 'double_faced_token', 'emblem']:
            return 'skip'

        # Verificar se ja existe
        from uuid import UUID
        try:
            card_uuid = UUID(card_data['id'])
            if card_uuid in existing_ids:
                return 'skip'
        except (ValueError, KeyError):
            return 'skip'

        layout = card_data.get('layout', 'normal')
        card_faces = card_data.get('card_faces', [])

        # Dados da face frontal
        image_uris = card_data.get('image_uris', {})
        front_face = {}
        back_face = {}

        # Para cartas de duas faces, extrair dados de cada face
        if card_faces and len(card_faces) >= 1:
            front_face = card_faces[0]
            # Se nao tem image_uris no nivel raiz, pegar da primeira face
            if not image_uris:
                image_uris = front_face.get('image_uris', {})

        if card_faces and len(card_faces) >= 2:
            back_face = card_faces[1]

        # Dados da face traseira (para DFCs)
        back_face_image_uris = back_face.get('image_uris', {})

        # Para cartas com faces, usar dados da face frontal se nao houver no nivel raiz
        mana_cost = card_data.get('mana_cost', '') or front_face.get('mana_cost', '')
        oracle_text = card_data.get('oracle_text', '') or front_face.get('oracle_text', '')
        type_line = card_data.get('type_line', '') or front_face.get('type_line', '')
        power = card_data.get('power') or front_face.get('power')
        toughness = card_data.get('toughness') or front_face.get('toughness')
        loyalty = card_data.get('loyalty') or front_face.get('loyalty')

        return Card(
            scryfall_id=card_data['id'],
            name=card_data.get('name', ''),
            mana_cost=mana_cost,
            cmc=card_data.get('cmc', 0),
            type_line=type_line,
            oracle_text=oracle_text,
            colors=','.join(card_data.get('colors', [])),
            color_identity=','.join(card_data.get('color_identity', [])),
            set_code=card_data.get('set', ''),
            set_name=card_data.get('set_name', ''),
            rarity=card_data.get('rarity', 'common'),
            image_small=image_uris.get('small', ''),
            image_normal=image_uris.get('normal', ''),
            image_large=image_uris.get('large', ''),
            power=power,
            toughness=toughness,
            loyalty=loyalty,
            # DFC support
            layout=layout,
            back_face_name=back_face.get('name'),
            back_face_mana_cost=back_face.get('mana_cost'),
            back_face_type_line=back_face.get('type_line'),
            back_face_oracle_text=back_face.get('oracle_text'),
            back_face_power=back_face.get('power'),
            back_face_toughness=back_face.get('toughness'),
            back_face_loyalty=back_face.get('loyalty'),
            back_face_image_small=back_face_image_uris.get('small'),
            back_face_image_normal=back_face_image_uris.get('normal'),
            back_face_image_large=back_face_image_uris.get('large'),
        )
