from django.urls import path
from .views import AvatarListCreateView, MeasurementsListCreateView

urlpatterns = [
    path('', AvatarListCreateView.as_view(), name='avatar-list'),
    path('<int:avatar_pk>/measurements', MeasurementsListCreateView.as_view(), name='measurements-list'),
]
