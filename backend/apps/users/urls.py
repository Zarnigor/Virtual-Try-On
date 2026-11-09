from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

# API contract: docs/04-data-model-and-api.md (frontend mirror: frontend/src/api/types.ts)
urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login, name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.me, name="me"),  # GET profile, DELETE account
]
