from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Avatar(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='avatars')
    name = models.CharField(max_length=100, default='My Avatar')

    def __str__(self):
        return f'{self.user.username} – {self.name}'


MEASUREMENT_VALIDATORS = {
    'height':   (MinValueValidator(140), MaxValueValidator(210)),
    'weight':   (MinValueValidator(35),  MaxValueValidator(200)),
    'shoulder': (MinValueValidator(30),  MaxValueValidator(60)),
    'chest':    (MinValueValidator(70),  MaxValueValidator(140)),
    'waist':    (MinValueValidator(50),  MaxValueValidator(130)),
    'hip':      (MinValueValidator(70),  MaxValueValidator(150)),
}


def _field(lo, hi, **kw):
    return models.FloatField(validators=[MinValueValidator(lo), MaxValueValidator(hi)], **kw)


class Measurements(models.Model):
    avatar = models.ForeignKey(Avatar, on_delete=models.CASCADE, related_name='measurements')
    height   = _field(140, 210)
    weight   = _field(35,  200)
    shoulder = _field(30,  60)
    chest    = _field(70,  140)
    waist    = _field(50,  130)
    hip      = _field(70,  150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.avatar} @ {self.created_at:%Y-%m-%d %H:%M}'
