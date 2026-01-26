"""Validador de decks Commander/EDH"""

from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass


BASIC_LANDS = {
    'Plains', 'Island', 'Swamp', 'Mountain', 'Forest',
    'Snow-Covered Plains', 'Snow-Covered Island',
    'Snow-Covered Swamp', 'Snow-Covered Mountain', 'Snow-Covered Forest',
    'Wastes'
}

RELENTLESS_CARDS = {
    'Relentless Rats',
    'Rat Colony',
    'Shadowborn Apostle',
    'Persistent Petitioners',
    "Dragon's Approach",
}


@dataclass
class ValidationError:
    code: str
    message: str
    card_name: Optional[str] = None


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[str]
    commander_name: Optional[str] = None
    partner_name: Optional[str] = None
    color_identity: str = ""
    card_count: int = 0


def parse_decklist(raw_text: str) -> Tuple[List[Tuple[int, str]], List[str]]:
    """
    Parseia texto do deck.
    Retorna: (lista de (quantidade, nome), linhas ignoradas)
    """
    cards = []
    ignored = []

    for line in raw_text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('//'):
            continue

        # Formatos suportados:
        # "1 Lightning Bolt"
        # "1x Lightning Bolt"
        # "Lightning Bolt"

        parts = line.split(' ', 1)
        if len(parts) == 1:
            cards.append((1, parts[0]))
        else:
            qty_str = parts[0].rstrip('x')
            try:
                qty = int(qty_str)
                cards.append((qty, parts[1].strip()))
            except ValueError:
                # Nao eh numero, assume nome completo
                cards.append((1, line))

    return cards, ignored


def is_valid_commander(card: dict) -> bool:
    """Verifica se carta pode ser comandante"""
    type_line = card.get('type_line', '').lower()
    oracle_text = (card.get('oracle_text') or '').lower()

    # Legendary Creature
    if 'legendary' in type_line and 'creature' in type_line:
        return True

    # Planeswalker com "can be your commander"
    if 'can be your commander' in oracle_text:
        return True

    return False


def has_partner(card: dict) -> bool:
    """Verifica se carta tem Partner"""
    oracle_text = (card.get('oracle_text') or '').lower()
    # "Partner" sozinho, nao "Partner with X"
    return 'partner' in oracle_text and 'partner with' not in oracle_text


def calculate_color_identity(commander: dict, partner: Optional[dict] = None) -> str:
    """Calcula identidade de cor combinada"""
    colors = set()

    for card in [commander, partner]:
        if card:
            identity = card.get('color_identity', '')
            if identity:
                colors.update(c.strip() for c in identity.split(',') if c.strip())

    # Ordenar WUBRG
    order = ['W', 'U', 'B', 'R', 'G']
    return ''.join(c for c in order if c in colors)


def validate_commander_deck(
    decklist: List[Tuple[int, str]],
    commander_name: str,
    card_lookup: Callable[[str], Optional[dict]],
    partner_name: Optional[str] = None
) -> ValidationResult:
    """
    Valida um deck Commander.

    Args:
        decklist: Lista de (quantidade, nome_carta)
        commander_name: Nome do comandante
        card_lookup: Funcao que recebe nome e retorna dict com dados da carta ou None
        partner_name: Nome do partner commander (opcional)

    Returns:
        ValidationResult com resultado da validacao
    """
    errors = []
    warnings = []

    # 1. Validar comandante
    commander = card_lookup(commander_name)
    if not commander:
        errors.append(ValidationError(
            'COMMANDER_NOT_FOUND',
            f'Comandante "{commander_name}" nao encontrado no banco de dados',
            commander_name
        ))
        return ValidationResult(False, errors, warnings)

    if not is_valid_commander(commander):
        errors.append(ValidationError(
            'INVALID_COMMANDER',
            f'"{commander_name}" nao pode ser comandante. Precisa ser Legendary Creature ou ter "can be your commander"',
            commander_name
        ))

    # 2. Validar partner se existir
    partner = None
    if partner_name:
        partner = card_lookup(partner_name)
        if not partner:
            errors.append(ValidationError(
                'PARTNER_NOT_FOUND',
                f'Partner "{partner_name}" nao encontrado no banco de dados',
                partner_name
            ))
        elif not is_valid_commander(partner):
            errors.append(ValidationError(
                'INVALID_PARTNER_COMMANDER',
                f'"{partner_name}" nao pode ser comandante',
                partner_name
            ))
        elif not has_partner(commander) or not has_partner(partner):
            errors.append(ValidationError(
                'INVALID_PARTNER',
                'Ambos comandantes precisam ter a habilidade Partner'
            ))

    # 3. Calcular identidade de cor
    color_identity = calculate_color_identity(commander, partner)
    color_identity_set = set(color_identity) if color_identity else set()

    # 4. Validar cada carta
    card_counts: Dict[str, int] = {}
    total_cards = 0
    cards_not_found = []

    for qty, name in decklist:
        # Pular se for o comandante (comum incluir na lista)
        if name.lower() == commander_name.lower():
            warnings.append(f'Comandante "{commander_name}" encontrado na lista principal - sera ignorado')
            continue
        if partner_name and name.lower() == partner_name.lower():
            warnings.append(f'Partner "{partner_name}" encontrado na lista principal - sera ignorado')
            continue

        card = card_lookup(name)
        if not card:
            cards_not_found.append(name)
            continue

        total_cards += qty
        card_counts[name] = card_counts.get(name, 0) + qty

        # Validar identidade de cor
        card_colors = card.get('color_identity', '')
        if card_colors:
            card_color_set = set(c.strip() for c in card_colors.split(',') if c.strip())
            if card_color_set and not card_color_set <= color_identity_set:
                invalid_colors = card_color_set - color_identity_set
                errors.append(ValidationError(
                    'COLOR_IDENTITY_VIOLATION',
                    f'"{name}" tem cores {invalid_colors} que nao estao na identidade do comandante ({color_identity or "Incolor"})',
                    name
                ))

    # Adicionar erros de cartas nao encontradas
    if cards_not_found:
        for name in cards_not_found[:5]:  # Limitar a 5
            errors.append(ValidationError(
                'CARD_NOT_FOUND',
                f'Carta "{name}" nao encontrada no banco de dados',
                name
            ))
        if len(cards_not_found) > 5:
            errors.append(ValidationError(
                'CARDS_NOT_FOUND',
                f'E mais {len(cards_not_found) - 5} cartas nao encontradas'
            ))

    # 5. Adicionar comandante(s) na contagem
    total_cards += 1
    if partner:
        total_cards += 1

    # 6. Validar total de 100 cartas
    if total_cards != 100:
        errors.append(ValidationError(
            'INVALID_CARD_COUNT',
            f'Deck tem {total_cards} cartas (precisa ter exatamente 100)'
        ))

    # 7. Validar singleton (exceto terrenos basicos e cartas especiais)
    for name, count in card_counts.items():
        if count > 1:
            if name in BASIC_LANDS:
                continue
            if name in RELENTLESS_CARDS:
                continue
            errors.append(ValidationError(
                'SINGLETON_VIOLATION',
                f'"{name}" tem {count} copias (Commander e formato singleton - maximo 1 copia)',
                name
            ))

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        commander_name=commander_name,
        partner_name=partner_name,
        color_identity=color_identity,
        card_count=total_cards
    )
