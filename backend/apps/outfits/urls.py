from django.urls import path
from . import views

# API contract: docs/04-data-model-and-api.md (frontend mirror: frontend/src/api/types.ts)
urlpatterns = [
    path("outfits/", views.list_outfits, name="outfits"),
    path("outfits/<int:pk>/", views.outfit_detail, name="outfit_detail"),  # GET, DELETE
]
