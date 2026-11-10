from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from fleet.models import AccountMembership, CompanyInvoice, FleetAccount
from .views import _create_customer_workspace


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TrialTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("trialowner")
        self.account = _create_customer_workspace(self.user, "Trial company")
        self.client.force_login(self.user)

    def expire(self):
        self.account.trial_ends_at = timezone.now() - timedelta(seconds=1)
        self.account.save(update_fields=["trial_ends_at"])

    def test_new_workspace_has_fourteen_days_and_no_invoice(self):
        self.assertEqual(self.account.trial_ends_at - self.account.trial_started_at, timedelta(days=14))
        self.assertFalse(CompanyInvoice.objects.exists())
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your 14-day free trial ends")

    def test_expiry_blocks_web_actions_but_preserves_data_and_logout(self):
        self.expire()
        for path in ["/dashboard/", "/marketplace/", "/load-sources/"]:
            self.assertContains(self.client.get(path), "Your free trial has ended", status_code=403)
        self.assertEqual(self.client.post("/trucks/add/", {"unit_number": "BLOCKED"}).status_code, 403)
        self.assertEqual(self.account.trucks.count(), 0)
        self.assertTrue(FleetAccount.objects.filter(pk=self.account.pk).exists())
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertFalse(CompanyInvoice.objects.exists())

    def test_mobile_expiry_and_logout(self):
        token = Token.objects.create(user=self.user)
        auth = {"HTTP_AUTHORIZATION": "Token " + token.key}
        self.assertEqual(self.client.get("/api/mobile/dashboard/", **auth).status_code, 200)
        self.expire()
        self.assertEqual(self.client.get("/api/mobile/dashboard/", **auth).status_code, 403)
        self.assertEqual(self.client.post("/api/mobile/logout/", **auth).status_code, 204)

    def test_existing_accounts_remain_unrestricted(self):
        legacy_user = get_user_model().objects.create_user("legacy")
        legacy = FleetAccount.objects.create(name="Existing account")
        AccountMembership.objects.create(user=legacy_user, account=legacy, role="owner")
        self.client.force_login(legacy_user)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        self.assertFalse(legacy.trial_expired)

    def test_trial_starts_on_signup_and_cannot_be_overridden(self):
        self.client.logout()
        response = self.client.post(reverse("sign_up"), {
            "username": "newtrial", "company_name": "New trial", "password1": "Strong-Sandbox-Password-2026!",
            "password2": "Strong-Sandbox-Password-2026!", "trial_ends_at": "2099-01-01",
        })
        self.assertEqual(response.status_code, 302)
        account = AccountMembership.objects.get(user__username="newtrial").account
        self.assertEqual(account.trial_ends_at - account.trial_started_at, timedelta(days=14))
        ends = account.trial_ends_at
        self.client.get(reverse("account_setup"))
        account.refresh_from_db()
        self.assertEqual(account.trial_ends_at, ends)
