from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from fleet.models import (
    AccountMembership, Company, CompanyInvoice, CompanyMembership,
    FleetAccount, Trailer, Truck,
)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class BillingTests(TestCase):
    def setUp(self):
        self.account = FleetAccount.objects.create(name="Test account")
        self.company = Company.objects.create(account=self.account, name="Customer A")
        self.other_account = FleetAccount.objects.create(name="Other account")
        self.other_company = Company.objects.create(account=self.other_account, name="Customer B")
        self.admin = get_user_model().objects.create_user(username="billing-admin")
        AccountMembership.objects.create(user=self.admin, account=self.account, role="owner")
        self.viewer = get_user_model().objects.create_user(username="client-viewer")
        CompanyMembership.objects.create(user=self.viewer, company=self.company, role="viewer")
        self.client.force_login(self.admin)

    def invoice(self, company=None, **extra):
        return CompanyInvoice.objects.create(
            company=company or self.company,
            period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
            due_date=date(2026, 11, 5), truck_count=2, trailer_count=3, **extra,
        )

    @patch("dashboard.views.timezone.localdate", return_value=date(2026, 10, 6))
    def test_creation_counts_active_trucks_and_all_company_trailers(self, _today):
        Truck.objects.create(account=self.account, company=self.company, unit_number="active")
        Truck.objects.create(account=self.account, company=self.company, unit_number="inactive", active=False)
        Truck.objects.create(account=self.other_account, company=self.other_company, unit_number="other")
        Trailer.objects.create(account=self.account, company=self.company, trailer_number="maintenance", status="Maintenance")
        response = self.client.post(reverse("billing"), {"company_id": self.company.pk})
        invoice = CompanyInvoice.objects.get()
        self.assertRedirects(response, reverse("invoice_detail", args=[invoice.pk]))
        self.assertEqual((invoice.truck_count, invoice.trailer_count), (1, 1))
        self.assertEqual(invoice.total, Decimal("45.00"))
        self.assertEqual(invoice.due_date, date(2026, 11, 5))

    def test_repeat_creation_preserves_original_quantities(self):
        self.client.post(reverse("billing"), {"company_id": self.company.pk})
        Truck.objects.create(account=self.account, company=self.company, unit_number="later")
        self.client.post(reverse("billing"), {"company_id": self.company.pk})
        self.assertEqual(CompanyInvoice.objects.count(), 1)
        self.assertEqual(CompanyInvoice.objects.get().truck_count, 0)

    def test_invalid_company_input_does_not_crash(self):
        for data in ({}, {"company_id": ""}, {"company_id": "bad"}):
            with self.subTest(data=data):
                self.assertRedirects(self.client.post(reverse("billing"), data), reverse("billing"))
        self.assertFalse(CompanyInvoice.objects.exists())

    def test_other_account_cannot_be_billed_or_viewed(self):
        invoice = self.invoice(company=self.other_company)
        self.assertEqual(self.client.post(reverse("billing"), {"company_id": self.other_company.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("invoice_detail", args=[invoice.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("billing")), "Customer B")

    def test_client_can_view_own_invoice_but_cannot_create_or_pay(self):
        invoice = self.invoice()
        self.client.force_login(self.viewer)
        url = reverse("invoice_detail", args=[invoice.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(reverse("billing"), {"company_id": self.company.pk}).status_code, 403)
        self.assertEqual(self.client.post(url, {"action": "mark_paid"}).status_code, 403)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "issued")

    def test_client_cannot_view_another_company_in_same_account(self):
        other = Company.objects.create(account=self.account, name="Private client")
        invoice = self.invoice(company=other)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("invoice_detail", args=[invoice.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("billing")), "Private client")

    def test_payment_records_actor_and_time_and_cannot_be_overwritten(self):
        invoice = self.invoice()
        url = reverse("invoice_detail", args=[invoice.pk])
        self.client.post(url, {"action": "mark_paid"})
        invoice.refresh_from_db()
        recorded_at = invoice.paid_at
        self.assertEqual(invoice.status, "paid")
        self.assertIsNotNone(recorded_at)
        self.assertEqual(invoice.paid_by, self.admin)
        self.assertEqual(invoice.total, Decimal("105.00"))
        self.assertEqual(invoice.amount_due, Decimal("0.00"))
        self.client.post(url, {"action": "mark_paid"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_at, recorded_at)
        self.assertContains(self.client.get(url), "Payment received.")
        self.assertNotContains(self.client.get(url), "Payment instructions:")

    def test_void_invoice_cannot_be_marked_paid(self):
        invoice = self.invoice(status="void")
        self.client.post(reverse("invoice_detail", args=[invoice.pk]), {"action": "mark_paid"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "void")
        self.assertIsNone(invoice.paid_at)
        self.assertEqual(invoice.amount_due, Decimal("0.00"))

    def test_issued_invoice_shows_full_balance(self):
        invoice = self.invoice()
        self.assertEqual(invoice.amount_due, Decimal("105.00"))
        self.assertContains(self.client.get(reverse("invoice_detail", args=[invoice.pk])), "Record full payment received")

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("billing"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
