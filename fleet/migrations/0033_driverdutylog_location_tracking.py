from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0032_driverdutylog"),
    ]

    operations = [
        migrations.AddField(
            model_name="driverdutylog",
            name="movement_distance_miles",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="driverdutylog",
            name="last_latitude",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="driverdutylog",
            name="last_longitude",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="driverdutylog",
            name="last_location_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
