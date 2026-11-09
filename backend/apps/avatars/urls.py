from django.urls import path
from . import views

urlpatterns = [
    path("avatars/", views.list_avatars, name="avatars_list"),
    path("avatars/nearest/", views.nearest_avatar, name="avatars_nearest"),
]
