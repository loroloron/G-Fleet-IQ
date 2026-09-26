from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.translation


def attach_legacy_records_to_account(apps, schema_editor):
    FleetAccount = apps.get_model("fleet", "FleetAccount")
    Company = apps.get_model("fleet", "Company")
    Customer = apps.get_model("fleet", "Customer")
    Driver = apps.get_model("fleet", "Driver")
    Truck = apps.get_model("fleet", "Truck")
    Trailer = apps.get_model("fleet", "Trailer")
    Load = apps.get_model("fleet", "Load")

    account, _ = FleetAccount.objects.using(schema_editor.connection.alias).get_or_create(
        name="G Fleet IQ Account"
    )
    database = schema_editor.connection.alias
    for model in (Company, Customer, Driver, Truck, Trailer, Load):
        model.objects.using(database).filter(account__isnull=True).update(account=account)


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0028_load_delivery_latitude_load_delivery_longitude"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FleetAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="G Fleet IQ Account", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="AccountMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("owner", django.utils.translation.gettext_lazy("Account owner")), ("dispatcher", django.utils.translation.gettext_lazy("Dispatcher")), ("viewer", django.utils.translation.gettext_lazy("Read only"))], default="viewer", max_length=20)),
                ("active", models.BooleanField(default=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="fleet.fleetaccount")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fleet_account_memberships", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="accountmembership",
            constraint=models.UniqueConstraint(fields=("user",), name="unique_user_fleet_account_membership"),
        ),
        migrations.AddField(
            model_name="company",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="clients", to="fleet.fleetaccount"),
        ),
        migrations.AddField(
            model_name="customer",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="customers", to="fleet.fleetaccount"),
        ),
        migrations.AddField(
            model_name="driver",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="drivers", to="fleet.fleetaccount"),
        ),
        migrations.AddField(
            model_name="truck",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="trucks", to="fleet.fleetaccount"),
        ),
        migrations.AddField(
            model_name="trailer",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="trailers", to="fleet.fleetaccount"),
        ),
        migrations.AddField(
            model_name="load",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="loads", to="fleet.fleetaccount"),
        ),
        migrations.RunPython(attach_legacy_records_to_account, migrations.RunPython.noop),
        *[
            migrations.AlterField(
                model_name=model_name,
                name="account",
                field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name=related_name, to="fleet.fleetaccount"),
            )
            for model_name, related_name in [
                ("company", "clients"),
                ("customer", "customers"),
                ("driver", "drivers"),
                ("truck", "trucks"),
                ("trailer", "trailers"),
                ("load", "loads"),
            ]
        ],
    ]
