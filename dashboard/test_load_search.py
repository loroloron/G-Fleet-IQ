from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from fleet.models import AccountMembership, FleetAccount, Customer, Load, Company, CompanyMembership


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class LoadSearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("search-owner")
        self.account = FleetAccount.objects.create(name="Fleet")
        AccountMembership.objects.create(user=self.user, account=self.account, role="owner")
        self.company = Company.objects.create(account=self.account, name="Client")
        self.customer = Customer.objects.create(account=self.account, name="Shipper")
        self.load = Load.objects.create(account=self.account, customer=self.customer, company=self.company, pickup="Indianapolis, IN", delivery="Chicago, IL", weight=20000, miles=200, rate=1000)
        other = FleetAccount.objects.create(name="Other")
        customer = Customer.objects.create(account=other, name="Private shipper")
        Load.objects.create(account=other, customer=customer, pickup="Secret", delivery="Secret")
        Load.objects.create(account=self.account, customer=self.customer, pickup="Completed", delivery="Chicago", status="Completed")
        self.client.force_login(self.user)

    def test_filters_and_isolation(self):
        response = self.client.get("/find-loads/?pickup=indiana&delivery=chicago&equipment=van&max_weight=25000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["load"] for row in response.context["rows"]], [self.load])
        self.assertContains(response, "External load boards are not connected")
        self.assertNotContains(response, "Secret")
        self.assertEqual(self.client.get("/find-loads/?max_weight=10000").context["page"].paginator.count, 0)

    def test_invalid_values_and_login(self):
        for query in ["max_weight=-1", "pickup_date=bad", "sort=unknown"]:
            response = self.client.get("/find-loads/?" + query)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(response.context["page"].paginator.count, 0)
        self.client.logout()
        self.assertEqual(self.client.get("/find-loads/").status_code, 302)

    def test_company_viewer_cannot_see_other_company(self):
        viewer = get_user_model().objects.create_user("viewer")
        CompanyMembership.objects.create(user=viewer, company=self.company, role="viewer")
        company = Company.objects.create(account=self.account, name="Other client")
        Load.objects.create(account=self.account, customer=self.customer, company=company, pickup="Hidden", delivery="Hidden")
        self.client.force_login(viewer)
        response = self.client.get("/find-loads/")
        self.assertEqual([row["load"] for row in response.context["rows"]], [self.load])
