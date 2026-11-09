from django.urls import path
from . import views

urlpatterns = [
    path("jobs/<int:pk>/", views.get_job, name="job_get"),
]
