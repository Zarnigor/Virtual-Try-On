from django.contrib import admin
from .models import Outfit, OutfitItem

class OutfitItemInline(admin.TabularInline):
    model = OutfitItem
    extra = 1

@admin.register(Outfit)
class OutfitAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'avatar', 'created_at')
    inlines = [OutfitItemInline]
