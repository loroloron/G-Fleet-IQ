from django.db import migrations, models
import django.db.models.deletion


def move_connections_to_single_client(apps, schema_editor):
    Connection = apps.get_model("fleet", "SamsaraConnection")
    Company = apps.get_model("fleet", "Company")
    for connection in Connection.objects.all().iterator():
        company_ids = list(
            Company.objects.filter(account_id=connection.account_id)
            .order_by("pk")
            .values_list("pk", flat=True)[:2]
        )
        if len(company_ids) == 1:
            connection.company_id = company_ids[0]
            connection.save(update_fields=["company"])
        else:
            # An account-level authorization cannot safely be assigned among
            # multiple client companies, so require those clients to connect again.
            connection.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0034_samsaraconnection"),
    ]

    operations = [
        migrations.AddField(
            model_name="samsaraconnection",
            name="company",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="samsara_connection",
                to="fleet.company",
            ),
        ),
        migrations.RunPython(move_connections_to_single_client, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="samsaraconnection",
            name="account",
        ),
        migrations.AlterField(
            model_name="samsaraconnection",
            name="company",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="samsara_connection",
                to="fleet.company",
            ),
        ),
    ]
