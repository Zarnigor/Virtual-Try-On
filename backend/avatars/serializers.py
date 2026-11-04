from rest_framework import serializers
from .models import Avatar, Measurements


class AvatarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Avatar
        fields = ('id', 'name')


class MeasurementsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Measurements
        fields = ('id', 'height', 'weight', 'shoulder', 'chest', 'waist', 'hip', 'created_at')
        read_only_fields = ('id', 'created_at')

    def validate(self, data):
        ranges = {
            'height':   (140, 210), 'weight':   (35, 200),
            'shoulder': (30, 60),   'chest':    (70, 140),
            'waist':    (50, 130),  'hip':      (70, 150),
        }
        for field, (lo, hi) in ranges.items():
            val = data.get(field)
            if val is not None and not (lo <= val <= hi):
                raise serializers.ValidationError({field: f'Must be between {lo} and {hi}.'})
        return data
