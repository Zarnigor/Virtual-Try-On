from django.urls import path
from . import views

urlpatterns = [
    path("tryon/", views.start_tryon, name="tryon_start"),
    path("config/", views.app_config, name="app_config"),
]
