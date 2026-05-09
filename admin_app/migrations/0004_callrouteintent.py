from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_app', '0003_delete_maskedcallsession'),
    ]

    operations = [
        migrations.CreateModel(
            name='CallRouteIntent',
            fields=[
                ('caller_key', models.CharField(max_length=10, primary_key=True, serialize=False)),
                ('destination', models.CharField(max_length=32)),
                ('created_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'call_route_intent',
            },
        ),
    ]
