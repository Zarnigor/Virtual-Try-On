from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Garment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='', max_length=100)),
                ('type', models.CharField(choices=[('tshirt', 'T-shirt'), ('pants', 'Pants')], max_length=20)),
                ('image', models.ImageField(upload_to='garments/')),
                ('original_image', models.ImageField(blank=True, null=True, upload_to='garments/originals/')),
                ('landmarks', models.JSONField(default=dict)),
                ('visibility', models.CharField(choices=[('private', 'Private'), ('public', 'Public')], default='private', max_length=10)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('review', 'Review'), ('hidden', 'Hidden')], default='pending', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='garments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'garments',
            },
        ),
    ]
