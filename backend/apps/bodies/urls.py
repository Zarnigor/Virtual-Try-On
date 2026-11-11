from django.urls import path
from . import views

# API contract: docs/04-data-model-and-api.md (frontend mirror: frontend/src/api/types.ts)
urlpatterns = [
    path("body/", views.body_root, name="body"),  # GET own, POST upload, DELETE
    path("body/confirm/", views.confirm_body, name="body_confirm"),
    path("body/sex/", views.set_body_sex, name="body_sex"),
    path("body/measurements/", views.update_measurements, name="body_measurements"),
]
