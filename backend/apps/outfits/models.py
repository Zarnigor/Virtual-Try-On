from django.db import models
from django.conf import settings


class Outfit(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="outfits",
    )
    body = models.ForeignKey(
        "bodies.Body",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="outfits",
    )
    avatar = models.ForeignKey(
        "avatars.Avatar",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="outfits",
    )
    garments = models.ManyToManyField("garments.Garment", related_name="outfits")
    result_image = models.ImageField(upload_to="outfits/", null=True, blank=True)
    realistic_image = models.ImageField(upload_to="outfits/realistic/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "outfits"
        ordering = ["-created_at"]
