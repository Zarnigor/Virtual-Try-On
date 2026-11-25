from django.urls import path
from . import views

urlpatterns = [
    path("tryon/", views.start_tryon, name="tryon_start"),
    path("tryon/fit-check/", views.fit_check, name="tryon_fit_check"),
    path("config/", views.app_config, name="app_config"),
]
