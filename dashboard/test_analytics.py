import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.signing import get_cookie_signer
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone

from fleet.models import FleetAccount, AccountMembership, Company
from .analytics import COOKIE
from .models import DailyActivity, DailyVisit


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AnalyticsTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("platform", is_superuser=True, is_staff=True)
        self.customer = get_user_model().objects.create_user("customer")
        self.workspace = FleetAccount.objects.create(name="Customer workspace")
        AccountMembership.objects.create(user=self.customer, account=self.workspace, role="owner")
        Company.objects.create(account=self.workspace, name="Customer trucking")

    def test_refresh_dedup_and_auth_activity(self):
        self.client.get("/")
        self.client.get("/")
        self.assertEqual(DailyVisit.objects.count(), 1)
        self.client.force_login(self.customer)
        self.client.get("/")
        self.client.get("/")
        self.assertEqual(DailyVisit.objects.count(), 1)
        self.assertEqual(DailyVisit.objects.get().user, self.customer)
        self.assertEqual(DailyActivity.objects.count(), 1)

    def test_customer_owner_is_denied(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get("/owner/analytics/").status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get("/owner/analytics/").status_code, 302)

    def test_platform_owner_needs_no_customer_membership(self):
        total_workspaces = FleetAccount.objects.count()
        self.client.force_login(self.owner)
        response = self.client.get("/owner/analytics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_accounts"], 1)
        self.assertEqual(response.context["total_workspaces"], total_workspaces)
        self.assertEqual(DailyVisit.objects.count(), 0)
        self.assertIn("no-store", response["Cache-Control"])

    def test_unique_users_across_browsers_and_period_filter(self):
        today = timezone.localdate()
        for _ in range(2):
            DailyVisit.objects.create(visitor_id=uuid.uuid4(), day=today, user=self.customer)
        DailyActivity.objects.create(user=self.customer, day=today)
        DailyActivity.objects.create(user=self.customer, day=today - timedelta(days=1))
        DailyVisit.objects.create(visitor_id=uuid.uuid4(), day=today - timedelta(days=8))
        self.client.force_login(self.owner)
        response = self.client.get("/owner/analytics/?days=7")
        self.assertEqual(response.context["visitors"], 2)
        self.assertEqual(response.context["active_users"], 1)
        self.assertEqual(len(response.context["rows"]), 7)
        self.assertEqual(self.client.get("/owner/analytics/?days=bad").context["days"], 7)

    def test_bots_and_tracking_failure_do_not_affect_app(self):
        self.assertEqual(self.client.get("/", HTTP_USER_AGENT="Googlebot").status_code, 200)
        self.assertFalse(DailyVisit.objects.exists())
        with patch("dashboard.analytics.DailyVisit.objects.get_or_create", side_effect=DatabaseError("offline")):
            with self.assertLogs("dashboard.analytics", level="ERROR"):
                self.assertEqual(self.client.get("/").status_code, 200)

    def test_signed_invalid_uuid_is_replaced(self):
        self.client.cookies[COOKIE] = get_cookie_signer(salt=COOKIE + COOKIE).sign("invalid")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(DailyVisit.objects.count(), 1)

    def test_explicit_platform_viewer_and_username_binding(self):
        self.client.force_login(self.customer)
        with override_settings(PLATFORM_ANALYTICS_USERS={str(self.customer.pk): "customer"}):
            self.assertEqual(self.client.get("/owner/analytics/").status_code, 200)
            self.client.get("/")
            self.assertFalse(DailyVisit.objects.exists())
        with override_settings(PLATFORM_ANALYTICS_USERS={str(self.customer.pk): "other"}):
            self.assertEqual(self.client.get("/owner/analytics/").status_code, 403)
