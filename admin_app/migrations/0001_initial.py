from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ArchivedUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_id', models.CharField(db_index=True, max_length=128)),
                ('email', models.CharField(blank=True, default='', max_length=255)),
                ('full_name', models.CharField(blank=True, default='', max_length=255)),
                ('phone', models.CharField(blank=True, default='', max_length=32)),
                ('original_created_at', models.DateTimeField(blank=True, null=True)),
                ('archived_at', models.DateTimeField(auto_now_add=True)),
                ('raw', models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.CreateModel(
            name='ArchivedVehicle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vehicle_id', models.CharField(db_index=True, max_length=128)),
                ('owner_id', models.CharField(db_index=True, max_length=128)),
                ('registration_number', models.CharField(blank=True, default='', max_length=64)),
                ('make', models.CharField(blank=True, default='', max_length=128)),
                ('model', models.CharField(blank=True, default='', max_length=128)),
                ('vehicle_type', models.CharField(blank=True, default='', max_length=64)),
                ('owner_contact', models.CharField(blank=True, default='', max_length=32)),
                ('qr_code_id', models.CharField(blank=True, default='', max_length=64)),
                ('original_created_at', models.DateTimeField(blank=True, null=True)),
                ('archived_at', models.DateTimeField(auto_now_add=True)),
                ('raw', models.JSONField(blank=True, default=dict)),
            ],
        ),
    ]

