from django.urls import path
from . import media_views

urlpatterns = [
    path("signed/<path:path>/", media_views.signed_media, name="signed_media"),
]
