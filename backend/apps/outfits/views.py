from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Outfit
from .serializers import OutfitSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_outfits(request):
    outfits = Outfit.objects.filter(user=request.user).prefetch_related("garments")
    return Response(OutfitSerializer(outfits, many=True, context={"request": request}).data)


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def outfit_detail(request, pk):
    try:
        outfit = Outfit.objects.get(pk=pk, user=request.user)
    except Outfit.DoesNotExist:
        return Response(status=404)
    if request.method == "DELETE":
        outfit.delete()
        return Response(status=204)
    return Response(OutfitSerializer(outfit, context={"request": request}).data)
