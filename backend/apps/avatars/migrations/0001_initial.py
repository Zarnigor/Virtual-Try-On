from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Avatar',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sex', models.CharField(choices=[('male', 'Male'), ('female', 'Female')], max_length=10)),
                ('build', models.CharField(choices=[('slim', 'Slim'), ('average', 'Average'), ('plus', 'Plus')], max_length=10)),
                ('image', models.ImageField(blank=True, null=True, upload_to='avatars/')),
                ('landmarks', models.JSONField(default=dict)),
                ('measurements', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'avatars',
                'unique_together': {('sex', 'build')},
            },
        ),
    ]
