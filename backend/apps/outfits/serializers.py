from rest_framework import serializers
from .models import Outfit
from apps.garments.serializers import GarmentSerializer
from apps.users.media_views import make_signed_url


class OutfitSerializer(serializers.ModelSerializer):
    garments = GarmentSerializer(many=True, read_only=True)
    result_url = serializers.SerializerMethodField()
    realistic_url = serializers.SerializerMethodField()

    class Meta:
        model = Outfit
        fields = ["id", "body", "avatar", "garments", "result_url", "realistic_url", "created_at"]
        read_only_fields = fields

    def _url(self, field):
        if not field:
            return None
        request = self.context.get("request")
        return make_signed_url(request, field.name) if request else None

    def get_result_url(self, obj):
        return self._url(obj.result_image)

    def get_realistic_url(self, obj):
        return self._url(obj.realistic_image)
