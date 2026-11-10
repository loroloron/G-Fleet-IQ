from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from fleet.models import AccountMembership, Company, CompanyMembership, Customer, FleetAccount, FreightPosting, Load


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class MarketplaceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("publisher")
        self.account = FleetAccount.objects.create(name="Publisher account")
        AccountMembership.objects.create(user=self.owner, account=self.account, role="owner")
        self.company = Company.objects.create(account=self.account, name="Publishing company")
        self.reader = get_user_model().objects.create_user("carrier")
        self.other_account = FleetAccount.objects.create(name="Carrier account")
        AccountMembership.objects.create(user=self.reader, account=self.other_account, role="owner")
        self.tomorrow = timezone.localdate() + timedelta(days=1)
        self.data = {
            "business_name": "Direct Shipper", "business_type": "shipper", "contact_name": "Sam",
            "contact_email": "sam@example.com", "contact_phone": "317-555-0100", "pickup": "Indianapolis, IN",
            "delivery": "Chicago, IL", "pickup_date": self.tomorrow.isoformat(), "equipment_type": "Dry Van",
            "weight": 25000, "rate": "1200.00", "expires_on": self.tomorrow.isoformat(),
            "share_confirmation": "on", "notes": "Dock pickup",
        }
        self.client.force_login(self.owner)

    def publish(self, **overrides):
        response = self.client.post("/marketplace/post/", {**self.data, **overrides})
        self.assertEqual(response.status_code, 302)
        return FreightPosting.objects.latest("pk")

    def test_cross_account_discovery_only_exposes_explicit_postings(self):
        posting = self.publish(account=self.other_account.pk, status="closed")
        self.assertEqual(posting.account, self.account)
        self.assertEqual(posting.status, "open")
        customer = Customer.objects.create(account=self.account, name="Private Customer")
        Load.objects.create(account=self.account, customer=customer, pickup="Private warehouse", delivery="Private delivery")
        self.client.force_login(self.reader)
        response = self.client.get("/marketplace/?pickup=indiana&delivery=chicago&equipment=van&max_weight=30000")
        self.assertContains(response, "Direct Shipper")
        self.assertNotContains(response, "Private warehouse")
        detail = self.client.get(f"/marketplace/{posting.pk}/")
        self.assertContains(detail, "sam@example.com")
        self.assertNotContains(detail, "Close posting")
        self.assertEqual(self.client.post(f"/marketplace/{posting.pk}/close/").status_code, 404)
        self.assertNotContains(self.client.get("/marketplace/?mine=1"), "Direct Shipper")

    def test_closing_is_post_only_and_removes_cross_account_access(self):
        posting = self.publish()
        self.assertEqual(self.client.get(f"/marketplace/{posting.pk}/close/").status_code, 405)
        self.assertEqual(self.client.post(f"/marketplace/{posting.pk}/close/").status_code, 302)
        self.assertContains(self.client.get(f"/marketplace/{posting.pk}/"), "no longer available")
        self.assertContains(self.client.get("/marketplace/?mine=1"), "Direct Shipper")
        self.client.force_login(self.reader)
        self.assertNotContains(self.client.get("/marketplace/"), "Direct Shipper")
        self.assertEqual(self.client.get(f"/marketplace/{posting.pk}/").status_code, 404)

    def test_validation_requires_consent_valid_dates_weight_and_rate(self):
        for overrides in [
            {"share_confirmation": ""}, {"weight": "0"}, {"rate": "-1"},
            {"contact_email": "bad"}, {"pickup_date": "bad"},
            {"pickup_date": (timezone.localdate() - timedelta(days=1)).isoformat()},
            {"expires_on": (self.tomorrow + timedelta(days=1)).isoformat()},
        ]:
            response = self.client.post("/marketplace/post/", {**self.data, **overrides})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertFalse(FreightPosting.objects.exists())

    def test_expiry_pickup_and_search_validation(self):
        posting = self.publish(rate="")
        self.assertContains(self.client.get("/marketplace/?sort=rate"), "Contact for rate")
        self.assertEqual(self.client.get("/marketplace/?max_weight=20000").context["page"].paginator.count, 0)
        response = self.client.get("/marketplace/?pickup_date=bad")
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(response.context["page"].paginator.count, 0)
        for field in ("expires_on", "pickup_date"):
            FreightPosting.objects.filter(pk=posting.pk).update(**{field: timezone.localdate() - timedelta(days=1)})
            self.client.force_login(self.reader)
            self.assertEqual(self.client.get(f"/marketplace/{posting.pk}/").status_code, 404)
            self.assertEqual(self.client.get("/marketplace/").context["page"].paginator.count, 0)
            FreightPosting.objects.filter(pk=posting.pk).update(**{field: self.tomorrow})

    def test_company_permissions_and_forged_company(self):
        dispatcher = get_user_model().objects.create_user("dispatcher")
        CompanyMembership.objects.create(user=dispatcher, company=self.company, role="dispatcher")
        other_company = Company.objects.create(account=self.account, name="Unrelated client")
        self.client.force_login(dispatcher)
        for company_id in ("", other_company.pk):
            response = self.client.post("/marketplace/post/", {**self.data, "company": company_id})
            self.assertTrue(response.context["form"].errors)
        posting = self.publish(company=self.company.pk)
        self.assertEqual(posting.company, self.company)
        viewer = get_user_model().objects.create_user("viewer")
        CompanyMembership.objects.create(user=viewer, company=self.company, role="viewer")
        self.client.force_login(viewer)
        self.assertContains(self.client.get("/marketplace/"), "Direct Shipper")
        self.assertEqual(self.client.get("/marketplace/post/").status_code, 403)
        self.assertEqual(self.client.post("/marketplace/post/", self.data).status_code, 403)
        self.assertEqual(self.client.post(f"/marketplace/{posting.pk}/close/").status_code, 403)

    def test_anonymous_and_csrf(self):
        self.client.logout()
        for url in ("/marketplace/", "/marketplace/post/", "/marketplace/1/"):
            self.assertEqual(self.client.get(url).status_code, 302)
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post("/marketplace/post/", self.data).status_code, 403)

    def test_load_sources_access_for_customer_and_read_only_member(self):
        response = self.client.get("/load-sources/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")
        self.assertContains(response, "Register")
        viewer = get_user_model().objects.create_user("sources-viewer")
        CompanyMembership.objects.create(user=viewer, company=self.company, role="viewer")
        self.client.force_login(viewer)
        self.assertEqual(self.client.get("/load-sources/").status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get("/load-sources/").status_code, 302)
