from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Avatar, Measurements
from .serializers import AvatarSerializer, MeasurementsSerializer


def get_owned_avatar_or_404(user, pk):
    try:
        return Avatar.objects.get(pk=pk, user=user)
    except Avatar.DoesNotExist:
        from rest_framework.exceptions import NotFound
        raise NotFound()


class AvatarListCreateView(generics.ListCreateAPIView):
    serializer_class = AvatarSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Avatar.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MeasurementsListCreateView(generics.ListCreateAPIView):
    serializer_class = MeasurementsSerializer
    permission_classes = [IsAuthenticated]

    def get_avatar(self):
        return get_owned_avatar_or_404(self.request.user, self.kwargs['avatar_pk'])

    def get_queryset(self):
        return Measurements.objects.filter(avatar=self.get_avatar())

    def perform_create(self, serializer):
        serializer.save(avatar=self.get_avatar())
