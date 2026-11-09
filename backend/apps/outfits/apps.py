from django.apps import AppConfig
from django.db.models.signals import post_delete


class OutfitsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.outfits"

    def ready(self):
        from apps.files import file_cleanup_receiver
        from .models import Outfit

        post_delete.connect(file_cleanup_receiver("result_image", "realistic_image"), sender=Outfit, weak=False,
                            dispatch_uid="outfits_file_cleanup")
