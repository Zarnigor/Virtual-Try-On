from django.apps import AppConfig
from django.db.models.signals import post_delete


class BodiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bodies"

    def ready(self):
        from apps.files import file_cleanup_receiver
        from .models import Body

        post_delete.connect(file_cleanup_receiver("image"), sender=Body, weak=False,
                            dispatch_uid="bodies_file_cleanup")
