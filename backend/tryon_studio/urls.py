from django.contrib import admin
from django.urls import path, include

# No open /media/ route: images are only served through signed URLs (/api/media/signed/..., docs/02 rule 10).
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.users.urls")),
    path("api/", include("apps.bodies.urls")),
    path("api/", include("apps.avatars.urls")),
    path("api/", include("apps.garments.urls")),
    path("api/", include("apps.tryon_engine.urls")),
    path("api/", include("apps.outfits.urls")),
    path("api/", include("apps.jobs.urls")),
    path("api/media/", include("apps.users.media_urls")),
]
