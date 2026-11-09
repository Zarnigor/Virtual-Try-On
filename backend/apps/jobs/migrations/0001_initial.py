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
            name='Job',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('body_validation', 'Body Validation'), ('garment_clean', 'Garment Clean'), ('tryon', 'Try-On'), ('moderation', 'Moderation'), ('realistic', 'Realistic Render')], max_length=20)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('done', 'Done'), ('failed', 'Failed')], default='queued', max_length=10)),
                ('target_id', models.IntegerField(blank=True, null=True)),
                ('result', models.JSONField(blank=True, null=True)),
                ('error_code', models.CharField(blank=True, default='', max_length=50)),
                ('error_detail', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'jobs',
            },
        ),
    ]
