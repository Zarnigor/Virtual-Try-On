from rest_framework import serializers

from catalog.serializers import ItemSerializer
from .models import Outfit, OutfitItem


class OutfitItemSerializer(serializers.ModelSerializer):
    item = ItemSerializer(read_only=True)
    item_id = serializers.PrimaryKeyRelatedField(
        source='item', queryset=__import__('catalog.models', fromlist=['Item']).Item.objects.all(),
        write_only=True,
    )

    class Meta:
        model = OutfitItem
        fields = ('id', 'item', 'item_id')


class OutfitSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    avatar_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Outfit
        fields = ('id', 'name', 'avatar_id', 'items', 'created_at')
        read_only_fields = ('id', 'created_at', 'items')

    def get_items(self, obj):
        qs = obj.outfit_items.select_related('item')
        return ItemSerializer(
            [oi.item for oi in qs],
            many=True,
            context=self.context,
        ).data

    def validate_avatar_id(self, value):
        from avatars.models import Avatar
        user = self.context['request'].user
        try:
            Avatar.objects.get(pk=value, user=user)
        except Avatar.DoesNotExist:
            raise serializers.ValidationError('Avatar not found or does not belong to you.')
        return value

    def create(self, validated_data):
        from avatars.models import Avatar
        avatar_id = validated_data.pop('avatar_id')
        avatar = Avatar.objects.get(pk=avatar_id)
        return Outfit.objects.create(avatar=avatar, **validated_data)
