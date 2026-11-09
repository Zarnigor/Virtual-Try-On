import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tryon_studio.settings.local")

app = Celery("tryon_studio")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
