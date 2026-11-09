from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    is_adult_confirmed = serializers.BooleanField()

    class Meta:
        model = User
        fields = ("email", "password", "is_adult_confirmed")

    def validate_is_adult_confirmed(self, v):
        if not v:
            raise serializers.ValidationError("18 yoshdan katta ekanligingizni tasdiqlang.")
        return v

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "is_adult_confirmed", "created_at")


class LoginSerializer(TokenObtainPairSerializer):
    username_field = "email"
