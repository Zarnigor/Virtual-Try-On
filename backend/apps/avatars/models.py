from django.db import models


class Avatar(models.Model):
    SEX_CHOICES = [("male", "Male"), ("female", "Female")]
    BUILD_CHOICES = [("slim", "Slim"), ("average", "Average"), ("plus", "Plus")]

    sex = models.CharField(max_length=10, choices=SEX_CHOICES)
    build = models.CharField(max_length=10, choices=BUILD_CHOICES)
    image = models.ImageField(upload_to="avatars/")
    landmarks = models.JSONField(default=dict)
    measurements = models.JSONField(default=dict)  # reference measurements in cm (circumference)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "avatars"
        unique_together = [("sex", "build")]

    def __str__(self):
        return f"{self.sex}_{self.build}"
