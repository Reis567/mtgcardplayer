from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Acessa um item de dicionario pelo nome da chave no template"""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def make_list(value):
    """Converte uma string em lista de caracteres"""
    if value is None:
        return []
    return list(str(value))
