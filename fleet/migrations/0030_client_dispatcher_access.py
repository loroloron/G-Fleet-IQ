from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.translation


def remove_legacy_account_dispatcher_roles(apps, schema_editor):
    AccountMembership = apps.get_model("fleet", "AccountMembership")
    database = schema_editor.connection.alias

    AccountMembership.objects.using(database).filter(
        role__in=["dispatcher", "viewer"]
    ).delete()


def fill_load_client_from_customer(apps, schema_editor):
    Load = apps.get_model("fleet", "Load")
    database = schema_editor.connection.alias
    loads = Load.objects.using(database).filter(company_id__isnull=True)
    rows = list(loads.values_list("pk", "customer__company_id"))
    for load_id, customer_company_id in rows:
        if customer_company_id:
            Load.objects.using(database).filter(pk=load_id).update(company_id=customer_company_id)


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0029_fleetaccount_membership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(fill_load_client_from_customer, migrations.RunPython.noop),
        migrations.CreateModel(
            name="CompanyMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("client_admin", django.utils.translation.gettext_lazy("Client administrator")), ("dispatcher", django.utils.translation.gettext_lazy("Dispatcher")), ("viewer", django.utils.translation.gettext_lazy("Read only"))], default="viewer", max_length=20)),
                ("active", models.BooleanField(default=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="fleet.company")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="client_memberships", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="companymembership",
            constraint=models.UniqueConstraint(fields=("user", "company"), name="unique_user_client_membership"),
        ),
        migrations.RunPython(remove_legacy_account_dispatcher_roles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="accountmembership",
            name="role",
            field=models.CharField(choices=[("owner", django.utils.translation.gettext_lazy("Account owner")), ("admin", django.utils.translation.gettext_lazy("Administrator"))], max_length=20),
        ),
    ]
