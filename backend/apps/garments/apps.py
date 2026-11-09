from django.apps import AppConfig
from django.db.models.signals import post_delete


class GarmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.garments"

    def ready(self):
        from apps.files import file_cleanup_receiver
        from .models import Garment

        post_delete.connect(file_cleanup_receiver("image", "original_image"), sender=Garment, weak=False,
                            dispatch_uid="garments_file_cleanup")
