from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0033_driverdutylog_location_tracking"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SamsaraConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("organization_id", models.CharField(blank=True, max_length=100)),
                ("organization_name", models.CharField(blank=True, max_length=200)),
                ("access_token_encrypted", models.TextField()),
                ("refresh_token_encrypted", models.TextField()),
                ("access_token_expires_at", models.DateTimeField()),
                ("scopes", models.CharField(blank=True, max_length=500)),
                ("connected_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="samsara_connection", to="fleet.fleetaccount")),
                ("connected_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="samsara_connections_created", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
