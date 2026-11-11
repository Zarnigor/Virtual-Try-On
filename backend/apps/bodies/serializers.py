from rest_framework import serializers
from .models import Body
from apps.users.media_views import make_signed_url

MEASUREMENT_KEYS = ("shoulder", "chest", "waist", "hip")


class BodySerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    measurements_unlock_at = serializers.SerializerMethodField()
    can_change_measurements = serializers.SerializerMethodField()

    class Meta:
        model = Body
        fields = (
            "id", "image_url", "sex", "landmarks", "height_cm", "measurements",
            "confirmed_at", "measurements_unlock_at", "can_change_measurements", "created_at",
        )
        read_only_fields = fields

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        if request:
            return make_signed_url(request, str(obj.image))
        return None

    def get_measurements_unlock_at(self, obj):
        return obj.measurements_unlock_at

    def get_can_change_measurements(self, obj):
        return obj.can_change_measurements


class BodyUploadSerializer(serializers.Serializer):
    photo = serializers.ImageField()
    is_adult_confirmed = serializers.BooleanField()
    sex = serializers.ChoiceField(choices=Body.SEX_CHOICES)

    def validate_is_adult_confirmed(self, v):
        if not v:
            raise serializers.ValidationError("18 yoshdan katta ekanligingizni tasdiqlang.")
        return v


class MeasurementsField(serializers.DictField):
    """Circumferences in cm: {shoulder?, chest?, waist?, hip?}. Unknown keys are rejected."""

    child = serializers.FloatField(min_value=1)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        unknown = set(value) - set(MEASUREMENT_KEYS)
        if unknown:
            raise serializers.ValidationError(f"Unknown keys: {', '.join(sorted(unknown))}")
        return value


class MeasurementsSerializer(serializers.Serializer):
    height_cm = serializers.FloatField(required=False, allow_null=True, min_value=50, max_value=260)
    measurements = MeasurementsField(required=False, allow_null=True)


class BodyConfirmSerializer(MeasurementsSerializer):
    """Confirm = send the final landmarks once; they are locked together with the photo."""

    landmarks = serializers.DictField()

    def validate_landmarks(self, v):
        if not v:
            raise serializers.ValidationError("Avval chiziqlarni belgilang.")
        return v
