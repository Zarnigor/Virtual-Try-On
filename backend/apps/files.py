"""Delete image files from storage when their database row is deleted.

Connected with post_delete in each app's AppConfig.ready(), so files go away however the row is
deleted: a view, a cascade (body -> outfits, user -> everything) or the Django admin.
"""
import logging

logger = logging.getLogger(__name__)


def delete_files(instance, *field_names):
    for name in field_names:
        f = getattr(instance, name, None)
        if f and f.name:
            try:
                f.storage.delete(f.name)
            except Exception:  # never block a delete because a file is already gone
                logger.warning("could not delete file for %s.%s", type(instance).__name__, name)


def file_cleanup_receiver(*field_names):
    def receiver(sender, instance, **kwargs):
        delete_files(instance, *field_names)
    return receiver
