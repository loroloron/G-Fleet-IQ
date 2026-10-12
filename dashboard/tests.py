from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class SignUpTests(TestCase):
    def setUp(self):
        self.initial_accounts = FleetAccount.objects.count()
        self.initial_companies = Company.objects.count()

    def test_signup_accepts_ten_character_username(self):
        response = self.client.post(reverse("sign_up"), {
            "company_name": "New Customer",
            "username": "fleettest1",
            "password1": "Strong-Sandbox-Password-2026!",
            "password2": "Strong-Sandbox-Password-2026!",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="fleettest1").exists())

    def test_signup_rejects_username_over_ten_characters(self):
        response = self.client.post(reverse("sign_up"), {
            "company_name": "New Customer",
            "username": "fleettest12",
            "password1": "Strong-Sandbox-Password-2026!",
            "password2": "Strong-Sandbox-Password-2026!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="fleettest12").exists())

    def test_existing_long_username_can_still_log_in(self):
        get_user_model().objects.create_user(
            username="existing-long-username", password="Strong-Sandbox-Password-2026!")
        response = self.client.post(reverse("login"), {
            "username": "existing-long-username",
            "password": "Strong-Sandbox-Password-2026!",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def signup(self, username, company_name):
        self.client.logout()
        return self.client.post(reverse("sign_up"), {
            "company_name": company_name,
            "username": username,
            "password1": "Strong-Sandbox-Password-2026!",
            "password2": "Strong-Sandbox-Password-2026!",
        })

    def test_signup_creates_private_workspace_and_opens_dashboard(self):
        self.assertEqual(self.signup("ownerone", "Customer One").status_code, 302)
        user = get_user_model().objects.get(username="ownerone")
        membership = AccountMembership.objects.get(user=user)
        self.assertEqual(membership.role, AccountMembership.ROLE_OWNER)
        self.assertEqual(membership.account.name, "Customer One")
        self.assertEqual(Company.objects.get(account=membership.account).name, "Customer One")
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("account_setup")).status_code, 302)

    def test_customers_cannot_view_or_edit_other_workspaces(self):
        self.signup("ownerone", "Customer One")
        first = AccountMembership.objects.get(user__username="ownerone").account
        company = Company.objects.get(account=first)
        truck = Truck.objects.create(account=first, company=company, unit_number="PRIVATE-ONE")
        invoice = CompanyInvoice.objects.create(
            company=company, period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31), due_date=date(2026, 11, 10), truck_count=1,
        )
        self.signup("ownertwo", "Customer Two")
        second = AccountMembership.objects.get(user__username="ownertwo").account
        self.assertNotEqual(first.pk, second.pk)
        self.assertNotContains(self.client.get(reverse("companies")), "Customer One")
        self.assertNotContains(self.client.get(reverse("trucks")), "PRIVATE-ONE")
        self.assertNotContains(self.client.get(reverse("billing")), invoice.invoice_number)
        self.assertEqual(self.client.get(reverse("invoice_detail", args=[invoice.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("edit_truck", args=[truck.pk]), {
            "unit_number": "CHANGED", "capacity": 40000, "company": company.pk, "active": True,
        }).status_code, 404)
        truck.refresh_from_db()
        self.assertEqual(truck.unit_number, "PRIVATE-ONE")
        response = self.client.post(reverse("billing"), {"company_id": company.pk})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(CompanyInvoice.objects.count(), 1)

    def test_duplicate_signup_does_not_create_another_workspace(self):
        self.signup("ownerone", "Customer One")
        response = self.signup("ownerone", "Duplicate Customer")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts + 1)
        self.assertEqual(Company.objects.count(), self.initial_companies + 1)

    def test_blank_company_name_is_rejected_without_creating_user(self):
        response = self.signup("ownerone", "   ")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="ownerone").exists())
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts)

    def test_workspace_failure_rolls_back_signup(self):
        with patch("dashboard.views.Company.objects.create", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.signup("ownerone", "Customer One")
        self.assertFalse(get_user_model().objects.filter(username="ownerone").exists())
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts)

    def test_legacy_unassigned_user_gets_own_workspace(self):
        existing = FleetAccount.objects.create(name="Existing owner workspace")
        owner = get_user_model().objects.create_user(username="oldowner")
        AccountMembership.objects.create(user=owner, account=existing, role="owner")
        user = get_user_model().objects.create_user(username="legacyuser")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("account_setup")).status_code, 200)
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts + 1)
        self.client.post(reverse("account_setup"), {"company_name": "Legacy Customer"})
        account = AccountMembership.objects.get(user=user).account
        self.assertNotEqual(account.pk, existing.pk)
        self.client.post(reverse("account_setup"), {"company_name": "Duplicate"})
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts + 2)

    def test_existing_client_access_and_revoked_access_are_preserved(self):
        account = FleetAccount.objects.create(name="Existing")
        company = Company.objects.create(account=account, name="Existing Client")
        user = get_user_model().objects.create_user(username="teamuser")
        membership = CompanyMembership.objects.create(user=user, company=company, role="viewer")
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse("account_setup"), {"company_name": "Other"}).status_code, 302)
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts + 1)
        membership.active = False
        membership.save(update_fields=["active"])
        self.assertEqual(self.client.post(reverse("account_setup"), {"company_name": "Other"}).status_code, 403)
        self.assertEqual(FleetAccount.objects.count(), self.initial_accounts + 1)

    def test_owner_cannot_move_another_customer_into_their_workspace(self):
        self.signup("ownerone", "Customer One")
        first_user = get_user_model().objects.get(username="ownerone")
        self.signup("ownertwo", "Customer Two")
        second = AccountMembership.objects.get(user__username="ownertwo").account
        self.client.force_login(first_user)
        response = self.client.post(reverse("account_team"), {
            "username": "ownertwo", "role": "admin",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AccountMembership.objects.get(user__username="ownertwo").account, second)


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
