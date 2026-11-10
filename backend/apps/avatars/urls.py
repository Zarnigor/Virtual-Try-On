from django.urls import path
from . import staff, views

urlpatterns = [
    path("avatars/", views.list_avatars, name="avatars_list"),
    path("avatars/nearest/", views.nearest_avatar, name="avatars_nearest"),
    path("staff/avatars/", staff.staff_avatars, name="staff_avatars"),
    path("staff/avatars/<int:pk>/", staff.staff_avatar_detail, name="staff_avatar_detail"),
    path("staff/avatars/<int:pk>/landmarks/", staff.staff_avatar_landmarks, name="staff_avatar_landmarks"),
]
