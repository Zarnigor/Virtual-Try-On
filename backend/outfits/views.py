from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Outfit
from .serializers import OutfitSerializer


class OutfitListCreateView(generics.ListCreateAPIView):
    serializer_class = OutfitSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Outfit.objects.filter(user=self.request.user).prefetch_related('outfit_items__item')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class OutfitDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = OutfitSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        try:
            return Outfit.objects.prefetch_related('outfit_items__item').get(
                pk=self.kwargs['pk'], user=self.request.user
            )
        except Outfit.DoesNotExist:
            raise NotFound()
