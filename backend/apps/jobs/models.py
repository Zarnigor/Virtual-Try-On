from django.db import models
from django.conf import settings


class Job(models.Model):
    KIND_CHOICES = [
        ("body_validation", "Body Validation"),
        ("garment_clean", "Garment Clean"),
        ("tryon", "Try-On"),
        ("moderation", "Moderation"),
        ("realistic", "Realistic Render"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jobs")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="queued")
    target_id = models.IntegerField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=50, blank=True, default="")
    error_detail = models.TextField(blank=True, default="")
    # Daily AI limit (apps/jobs/limits.py). ai_called is an audit flag set before the request, never cleared.
    AI_OUTCOME_CHOICES = [
        ("", "In flight / none"), ("responded", "Responded"), ("invalid", "Invalid reply"),
        ("unavailable", "AI unavailable"),
    ]
    ai_called = models.BooleanField(default=False)
    ai_called_at = models.DateTimeField(null=True, blank=True)
    ai_outcome = models.CharField(max_length=12, choices=AI_OUTCOME_CHOICES, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "jobs"
