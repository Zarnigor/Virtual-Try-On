from django.db import models
from django.conf import settings


class Garment(models.Model):
    TYPE_CHOICES = [("tshirt", "T-shirt"), ("pants", "Pants")]
    VIS_CHOICES = [("private", "Private"), ("public", "Public")]
    STATUS_CHOICES = [
        ("pending", "Pending"), ("approved", "Approved"),
        ("review", "Review"), ("hidden", "Hidden"),
    ]
    # docs/09 #93: garment fit is per garment. adapt = fully deformed to the body landmarks (current engine);
    # keep_shape = keeps its own proportions (oversized, wide-leg), only anchors fit the body (engine: pending).
    FIT_CHOICES = [("adapt", "Adapt to body"), ("keep_shape", "Keep own shape")]
    GENDER_CHOICES = [("female", "Female"), ("male", "Male"), ("unisex", "Unisex")]

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
    fit_mode = models.CharField(max_length=12, choices=FIT_CHOICES, default="adapt")
    gender = models.CharField(max_length=8, choices=GENDER_CHOICES, default="unisex")
    # True = the AI check was skipped (AI_DEV_BYPASS, local dev only): this garment was NOT validated.
    ai_skipped = models.BooleanField(default=False)
    # The stored PNG had its photo lighting flattened (apps/garments/lighting.py); never flatten twice.
    lighting_flattened = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "garments"
