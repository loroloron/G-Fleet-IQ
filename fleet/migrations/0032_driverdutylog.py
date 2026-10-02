from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0031_driver_mobile_checkins"),
    ]

    operations = [
        migrations.CreateModel(
            name="DriverDutyLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("off_duty", "Off duty"), ("on_duty", "On duty, not driving"), ("driving", "Driving")], max_length=20)),
                ("source", models.CharField(choices=[("manual", "Manual"), ("automatic", "Automatic movement detection")], default="manual", max_length=12)),
                ("started_at", models.DateTimeField()),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="driver_duty_logs", to="fleet.fleetaccount")),
                ("driver", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="duty_logs", to="fleet.driver")),
            ],
            options={
                "ordering": ["started_at", "id"],
                "indexes": [
                    models.Index(fields=["account", "started_at"], name="duty_account_start_idx"),
                    models.Index(fields=["driver", "started_at"], name="duty_driver_start_idx"),
                ],
            },
        ),
    ]
