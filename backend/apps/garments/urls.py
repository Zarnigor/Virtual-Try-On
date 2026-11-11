from django.urls import path
from . import views

# API contract: docs/04-data-model-and-api.md (frontend mirror: frontend/src/api/types.ts)
urlpatterns = [
    path("garments/", views.garments_root, name="garments"),  # GET list, POST upload
    path("garments/<int:pk>/", views.garment_detail, name="garment_detail"),  # GET, PATCH (fit_mode, gender), DELETE
    path("garments/<int:pk>/landmarks/", views.update_landmarks, name="garment_landmarks"),
    path("garments/<int:pk>/visibility/", views.update_visibility, name="garment_visibility"),
]
