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
            name='Body',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='bodies/')),
                ('landmarks', models.JSONField(default=dict)),
                ('height_cm', models.FloatField(blank=True, null=True)),
                ('measurements', models.JSONField(blank=True, null=True)),
                ('measurements_changed_at', models.DateTimeField(blank=True, null=True)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='body', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'bodies',
            },
        ),
    ]
