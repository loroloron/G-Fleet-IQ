from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0035_samsaraconnection_per_company"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyInvoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("due_date", models.DateField()),
                ("truck_count", models.PositiveIntegerField(default=0)),
                ("trailer_count", models.PositiveIntegerField(default=0)),
                ("truck_rate", models.DecimalField(decimal_places=2, default="30.00", max_digits=8)),
                ("trailer_rate", models.DecimalField(decimal_places=2, default="15.00", max_digits=8)),
                ("status", models.CharField(choices=[("issued", _("Issued")), ("paid", _("Paid")), ("void", _("Void"))], default="issued", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="company_invoices_created", to=settings.AUTH_USER_MODEL)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invoices", to="fleet.company")),
            ],
            options={
                "ordering": ["-period_start", "company__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="companyinvoice",
            constraint=models.UniqueConstraint(fields=("company", "period_start", "period_end"), name="unique_company_invoice_period"),
        ),
    ]
