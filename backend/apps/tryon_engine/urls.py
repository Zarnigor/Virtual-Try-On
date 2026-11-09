from django.urls import path
from . import views

urlpatterns = [
    path("tryon/", views.start_tryon, name="tryon_start"),
]
