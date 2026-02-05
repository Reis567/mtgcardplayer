from django.db import models


class Card(models.Model):
    RARITY_CHOICES = [
        ('common', 'Common'),
        ('uncommon', 'Uncommon'),
        ('rare', 'Rare'),
        ('mythic', 'Mythic'),
        ('special', 'Special'),
        ('bonus', 'Bonus'),
    ]

    # Layouts que possuem duas faces
    DOUBLE_FACED_LAYOUTS = [
        'transform',        # Werewolves, Innistrad (vira ao transformar)
        'modal_dfc',        # MDFCs de Zendikar/Strixhaven (escolhe qual lado jogar)
        'reversible_card',  # Cartas reversiveis
        'flip',             # Cartas flip de Kamigawa (viram de cabeca pra baixo)
        'meld',             # Cartas que combinam (Brisela, etc)
    ]

    scryfall_id = models.UUIDField(unique=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    mana_cost = models.CharField(max_length=100, blank=True, null=True)
    cmc = models.FloatField(default=0)
    type_line = models.CharField(max_length=255, db_index=True)
    oracle_text = models.TextField(blank=True, null=True)
    colors = models.CharField(max_length=50, blank=True, default='')
    color_identity = models.CharField(max_length=50, blank=True, default='')
    set_code = models.CharField(max_length=10, db_index=True)
    set_name = models.CharField(max_length=255)
    rarity = models.CharField(max_length=20, choices=RARITY_CHOICES)
    image_small = models.URLField(max_length=500, blank=True, null=True)
    image_normal = models.URLField(max_length=500, blank=True, null=True)
    image_large = models.URLField(max_length=500, blank=True, null=True)
    power = models.CharField(max_length=10, blank=True, null=True)
    toughness = models.CharField(max_length=10, blank=True, null=True)
    loyalty = models.CharField(max_length=10, blank=True, null=True)

    # Double-Faced Card (DFC) support
    layout = models.CharField(max_length=30, blank=True, default='normal')

    # Back face data (para transform, modal_dfc, flip, etc)
    back_face_name = models.CharField(max_length=255, blank=True, null=True)
    back_face_mana_cost = models.CharField(max_length=100, blank=True, null=True)
    back_face_type_line = models.CharField(max_length=255, blank=True, null=True)
    back_face_oracle_text = models.TextField(blank=True, null=True)
    back_face_power = models.CharField(max_length=10, blank=True, null=True)
    back_face_toughness = models.CharField(max_length=10, blank=True, null=True)
    back_face_loyalty = models.CharField(max_length=10, blank=True, null=True)
    back_face_image_small = models.URLField(max_length=500, blank=True, null=True)
    back_face_image_normal = models.URLField(max_length=500, blank=True, null=True)
    back_face_image_large = models.URLField(max_length=500, blank=True, null=True)

    def is_double_faced(self):
        """Retorna True se a carta tem duas faces"""
        return self.layout in self.DOUBLE_FACED_LAYOUTS

    def is_transformable(self):
        """Retorna True se a carta pode transformar durante o jogo"""
        return self.layout in ['transform', 'flip']

    def is_modal(self):
        """Retorna True se e MDFC (escolhe qual lado jogar)"""
        return self.layout == 'modal_dfc'

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.set_code.upper()})"

    def get_colors_display(self):
        if not self.colors:
            return 'Colorless'
        color_map = {'W': 'White', 'U': 'Blue', 'B': 'Black', 'R': 'Red', 'G': 'Green'}
        return ', '.join(color_map.get(c, c) for c in self.colors.split(',') if c)
