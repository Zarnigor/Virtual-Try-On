import io
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image

from avatars.models import Avatar, Measurements
from catalog.models import Item


def make_png(color_rgba, label, text_color=(255, 255, 255, 255)):
    img = Image.new('RGBA', (600, 1200), color=color_rgba)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


DEMO_ITEMS = [
    dict(name='Demo Top 1',    category='top',    region='torso', fit_measure='chest', z_index=20, color=(180, 120, 200, 200)),
    dict(name='Demo Top 2',    category='top',    region='torso', fit_measure='chest', z_index=20, color=(220, 100, 140, 200)),
    dict(name='Demo Bottom 1', category='bottom', region='legs',  fit_measure='hip',   z_index=10, color=(100, 140, 220, 200)),
]


class Command(BaseCommand):
    help = 'Seed database with a demo user, avatar, measurements, and placeholder items.'

    def handle(self, *args, **options):
        # User
        user, created = User.objects.get_or_create(
            username='demo',
            defaults={'email': 'demo@example.com'},
        )
        if created:
            user.set_password('demo1234')
            user.save()
            self.stdout.write('  Created user: demo / demo1234')
        else:
            self.stdout.write('  User demo already exists.')

        # Avatar
        avatar, _ = Avatar.objects.get_or_create(user=user, defaults={'name': 'Demo Avatar'})

        # Measurements
        if not Measurements.objects.filter(avatar=avatar).exists():
            Measurements.objects.create(
                avatar=avatar,
                height=165, weight=60, shoulder=38, chest=88, waist=68, hip=95,
            )
            self.stdout.write('  Created measurements.')

        # Items
        for item_data in DEMO_ITEMS:
            if Item.objects.filter(name=item_data['name']).exists():
                self.stdout.write(f"  Item '{item_data['name']}' already exists.")
                continue
            png_bytes = make_png(item_data['color'], item_data['name'])
            item = Item(
                name=item_data['name'],
                category=item_data['category'],
                region=item_data['region'],
                fit_measure=item_data['fit_measure'],
                z_index=item_data['z_index'],
            )
            filename = item_data['name'].lower().replace(' ', '-') + '.png'
            item.image.save(filename, ContentFile(png_bytes), save=False)
            item.save()
            self.stdout.write(f"  Created item: {item_data['name']}")

        self.stdout.write(self.style.SUCCESS('Demo seed complete.'))
