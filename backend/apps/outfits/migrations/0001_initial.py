from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('bodies', '0001_initial'),
        ('avatars', '0001_initial'),
        ('garments', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Outfit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('result_image', models.ImageField(blank=True, null=True, upload_to='outfits/')),
                ('realistic_image', models.ImageField(blank=True, null=True, upload_to='outfits/realistic/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='outfits', to=settings.AUTH_USER_MODEL)),
                ('body', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='outfits', to='bodies.body')),
                ('avatar', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='outfits', to='avatars.avatar')),
                ('garments', models.ManyToManyField(related_name='outfits', to='garments.garment')),
            ],
            options={
                'db_table': 'outfits',
                'ordering': ['-created_at'],
            },
        ),
    ]
