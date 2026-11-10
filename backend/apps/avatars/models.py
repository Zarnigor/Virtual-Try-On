from django.db import models


class Avatar(models.Model):
    SEX_CHOICES = [("male", "Male"), ("female", "Female")]
    BUILD_CHOICES = [("slim", "Slim"), ("average", "Average"), ("plus", "Plus")]

    sex = models.CharField(max_length=10, choices=SEX_CHOICES)
    build = models.CharField(max_length=10, choices=BUILD_CHOICES)
    image = models.ImageField(upload_to="avatars/", blank=True, null=True)  # set right after creation by seed_avatars
    landmarks = models.JSONField(default=dict)
    measurements = models.JSONField(default=dict)  # reference measurements in cm (circumference)
    height_cm = models.FloatField(null=True, blank=True)  # nominal height, for px -> cm in the staff editor
    # Set when staff save the landmarks in the editor; null = still the auto-detected starting point.
    landmarks_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "avatars"
        unique_together = [("sex", "build")]

    def __str__(self):
        return f"{self.sex}_{self.build}"
