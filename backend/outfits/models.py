from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models

from avatars.models import Avatar
from catalog.models import Item


class Outfit(models.Model):
    user   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='outfits')
    avatar = models.ForeignKey(Avatar, on_delete=models.CASCADE, related_name='outfits')
    name   = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} – {self.name}'


class OutfitItem(models.Model):
    outfit = models.ForeignKey(Outfit, on_delete=models.CASCADE, related_name='outfit_items')
    item   = models.ForeignKey(Item, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('outfit', 'item')

    def clean(self):
        # At most one top and one bottom per outfit
        category = self.item.category
        existing = self.outfit.outfit_items.exclude(pk=self.pk).filter(item__category=category)
        if existing.exists():
            raise ValidationError(f'An outfit can have at most one {category}.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.outfit} + {self.item}'
