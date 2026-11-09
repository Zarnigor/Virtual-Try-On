from django.db import models
from django.conf import settings


class Garment(models.Model):
    TYPE_CHOICES = [("tshirt", "T-shirt"), ("pants", "Pants")]
    VIS_CHOICES = [("private", "Private"), ("public", "Public")]
    STATUS_CHOICES = [
        ("pending", "Pending"), ("approved", "Approved"),
        ("review", "Review"), ("hidden", "Hidden"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,  # null = admin catalog garment
        on_delete=models.CASCADE,  # account deletion deletes the user's garments (docs/07)
        related_name="garments",
    )
    name = models.CharField(max_length=100, default="")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    image = models.ImageField(upload_to="garments/")
    original_image = models.ImageField(upload_to="garments/originals/", null=True, blank=True)
    landmarks = models.JSONField(default=dict)
    visibility = models.CharField(max_length=10, choices=VIS_CHOICES, default="private")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "garments"
