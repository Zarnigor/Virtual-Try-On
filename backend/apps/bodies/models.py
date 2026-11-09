from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


class Body(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="body",
    )
    image = models.ImageField(upload_to="bodies/")
    landmarks = models.JSONField(default=dict)
    height_cm = models.FloatField(null=True, blank=True)
    measurements = models.JSONField(null=True, blank=True)
    measurements_changed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bodies"

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    @property
    def measurements_unlock_at(self):
        if self.measurements_changed_at:
            return self.measurements_changed_at + timedelta(days=365)
        return None

    @property
    def can_change_measurements(self):
        if not self.measurements_changed_at:
            return True
        return timezone.now() >= self.measurements_unlock_at
