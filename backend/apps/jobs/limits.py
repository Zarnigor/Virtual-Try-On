"""Race-safe daily limits on AI-reaching attempts (docs/09 #29), one limit per job kind (docs/09 #52):
body checks use settings.AI_DAILY_LIMIT, garment checks settings.AI_GARMENT_DAILY_LIMIT.

Staff users are exempt from the GARMENT limit (they curate the catalog): the slot is still reserved and the AI
check still runs, only the count is skipped. The body limit applies to everyone.

A slot is reserved (job.ai_called = True) under a lock on the user row BEFORE the request is sent.
Counted: replies (`responded`, including photo rejections), `invalid` replies and in-flight jobs.
Not counted: `unavailable` (the AI could not answer), code-check rejections, bypassed jobs and cache hits
(none of those reserve a slot).
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.users.models import User

from .models import Job

DAY_TZ = ZoneInfo("Asia/Tashkent")
STAFF_EXEMPT_KINDS = {"garment_clean"}
LIMIT_SETTING = {"body_validation": "AI_DAILY_LIMIT", "garment_clean": "AI_GARMENT_DAILY_LIMIT"}


def limit_for(kind: str) -> int:
    return getattr(settings, LIMIT_SETTING[kind])


def _today_start():
    now = timezone.now().astimezone(DAY_TZ)
    return datetime.combine(now.date(), time.min, tzinfo=DAY_TZ)


def counted_today(user_id: int, kind: str) -> int:
    return (
        Job.objects.filter(user_id=user_id, kind=kind, ai_called=True, ai_called_at__gte=_today_start())
        .exclude(ai_outcome="unavailable")
        .count()
    )


def reserve_ai_slot(job: Job) -> bool:
    """True if a slot was reserved for this job; False if the user has used today's limit."""
    with transaction.atomic():
        user = User.objects.select_for_update().only("pk", "is_staff").get(pk=job.user_id)
        exempt = user.is_staff and job.kind in STAFF_EXEMPT_KINDS
        if not exempt and counted_today(job.user_id, job.kind) >= limit_for(job.kind):
            return False
        job.ai_called = True
        job.ai_called_at = timezone.now()
        job.ai_outcome = ""
        job.save(update_fields=["ai_called", "ai_called_at", "ai_outcome", "updated_at"])
    return True


def set_outcome(job: Job, outcome: str) -> None:
    job.ai_outcome = outcome
    job.save(update_fields=["ai_outcome", "updated_at"])
