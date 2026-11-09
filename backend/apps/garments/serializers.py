from rest_framework import serializers
from .models import Garment
from apps.users.media_views import make_signed_url


class GarmentSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    thumb_url = serializers.SerializerMethodField()
    owned_by_me = serializers.SerializerMethodField()
    original_preview_url = serializers.SerializerMethodField()

    class Meta:
        model = Garment
        fields = (
            "id", "name", "type", "image_url", "thumb_url", "original_preview_url",
            "width", "height", "landmarks", "visibility", "status", "owned_by_me", "created_at",
        )
        read_only_fields = fields

    width = serializers.SerializerMethodField()
    height = serializers.SerializerMethodField()

    def _dims(self, obj):
        try:
            return obj.image.width, obj.image.height
        except Exception:  # missing file or not processed yet
            return None, None

    def get_width(self, obj):
        return self._dims(obj)[0]

    def get_height(self, obj):
        return self._dims(obj)[1]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        return make_signed_url(request, str(obj.image)) if request else None

    def get_thumb_url(self, obj):
        return self.get_image_url(obj)

    def get_original_preview_url(self, obj):
        if not obj.original_image:
            return None
        request = self.context.get("request")
        return make_signed_url(request, str(obj.original_image)) if request else None

    def get_owned_by_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.owner_id == request.user.id
        return False


class GarmentUploadSerializer(serializers.Serializer):
    photo = serializers.ImageField()
    type = serializers.ChoiceField(choices=["tshirt", "pants"])
    name = serializers.CharField(max_length=100, required=False, default="")
