from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_app', '0004_callrouteintent'),
    ]

    operations = [
        migrations.CreateModel(
            name='ActivationEmailOtp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.CharField(db_index=True, max_length=255)),
                ('qr_id', models.CharField(max_length=64)),
                ('code_hash', models.CharField(max_length=64)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('expires_at', models.DateTimeField()),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('consumed', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'activation_email_otp',
            },
        ),
    ]
