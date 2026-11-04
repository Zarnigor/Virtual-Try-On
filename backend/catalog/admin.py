from django.contrib import admin
from django.utils.html import format_html
from .models import Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display   = ('name', 'category', 'region', 'fit_measure', 'z_index', 'image_preview')
    list_filter    = ('category',)
    search_fields  = ('name',)
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:80px; border-radius:6px;" />',
                obj.image.url
            )
        return '—'
    image_preview.short_description = 'Preview'
