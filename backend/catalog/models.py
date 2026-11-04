from django.core.exceptions import ValidationError
from django.db import models
from PIL import Image


def validate_item_image(image):
    img = Image.open(image)
    if img.format != 'PNG':
        raise ValidationError('Image must be a PNG file.')
    if img.size != (600, 1200):
        raise ValidationError(f'Image must be exactly 600×1200 px (got {img.size[0]}×{img.size[1]}).')
    image.seek(0)
    if image.size > 2 * 1024 * 1024:
        raise ValidationError('Image must be 2 MB or smaller.')


CATEGORY_CHOICES = [('top', 'Top'), ('bottom', 'Bottom')]
REGION_CHOICES = [('torso', 'Torso'), ('legs', 'Legs')]
FIT_MEASURE_CHOICES = [('chest', 'Chest'), ('hip', 'Hip')]

CONSISTENCY = {
    'top':    {'region': 'torso', 'fit_measure': 'chest'},
    'bottom': {'region': 'legs',  'fit_measure': 'hip'},
}


class Item(models.Model):
    name        = models.CharField(max_length=100)
    category    = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    region      = models.CharField(max_length=10, choices=REGION_CHOICES)
    fit_measure = models.CharField(max_length=10, choices=FIT_MEASURE_CHOICES)
    image       = models.ImageField(upload_to='items/', validators=[validate_item_image])
    z_index     = models.PositiveSmallIntegerField(default=10)

    def clean(self):
        expected = CONSISTENCY.get(self.category, {})
        errors = {}
        if self.region and self.region != expected.get('region'):
            errors['region'] = f"A {self.category} must have region='{expected['region']}'."
        if self.fit_measure and self.fit_measure != expected.get('fit_measure'):
            errors['fit_measure'] = f"A {self.category} must have fit_measure='{expected['fit_measure']}'."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name
