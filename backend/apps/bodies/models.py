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
    SEX_CHOICES = [("male", "Male"), ("female", "Female")]

    image = models.ImageField(upload_to="bodies/")
    # Chosen by the user at upload (required there). Null only on bodies created before 2026-11-11: the UI asks
    # for a one-time re-choice (PATCH body/sex/), never guessed. Try-on uses it for the garment gender rule.
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, null=True, blank=True)
    landmarks = models.JSONField(default=dict)
    height_cm = models.FloatField(null=True, blank=True)
    measurements = models.JSONField(null=True, blank=True)
    measurements_changed_at = models.DateTimeField(null=True, blank=True)
    # measurements.shoulder_width was computed from the landmarks at confirm (docs/09 #130), not entered by the user.
    # A PATCH that changes height_cm recomputes it while this is true; a user-entered value sets it to False.
    shoulder_width_estimated = models.BooleanField(default=False)
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
