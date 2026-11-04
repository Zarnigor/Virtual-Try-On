from rest_framework import serializers
from .models import Item, CONSISTENCY


class ItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ('id', 'name', 'image_url', 'category', 'region', 'fit_measure', 'z_index')

    def get_image_url(self, obj):
        request = self.context.get('request')
        if request and obj.image:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else None

    def validate(self, data):
        category = data.get('category', getattr(self.instance, 'category', None))
        expected = CONSISTENCY.get(category, {})
        errors = {}
        region = data.get('region', getattr(self.instance, 'region', None))
        fit = data.get('fit_measure', getattr(self.instance, 'fit_measure', None))
        if region and region != expected.get('region'):
            errors['region'] = f"A {category} must have region='{expected['region']}'."
        if fit and fit != expected.get('fit_measure'):
            errors['fit_measure'] = f"A {category} must have fit_measure='{expected['fit_measure']}'."
        if errors:
            raise serializers.ValidationError(errors)
        return data
