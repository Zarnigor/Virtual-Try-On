from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from .models import Item
from .serializers import ItemSerializer


class ItemListView(generics.ListAPIView):
    queryset = Item.objects.all().order_by('z_index', 'name')
    serializer_class = ItemSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['category']
