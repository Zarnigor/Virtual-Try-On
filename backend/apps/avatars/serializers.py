from rest_framework import serializers
from .models import Avatar
from apps.users.media_views import make_signed_url


class AvatarSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Avatar
        fields = ("id", "sex", "build", "image_url", "landmarks", "measurements")

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        if request:
            return make_signed_url(request, str(obj.image))
        return None
