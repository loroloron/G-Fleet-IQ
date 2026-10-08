from datetime import date
from decimal import Decimal
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from fleet.models import AccountMembership, Company, CompanyInvoice, CompanyMembership, FleetAccount, InvoicePayment
from . import payments
import stripe


@override_settings(
    STRIPE_SECRET_KEY="sk_test_example", STRIPE_WEBHOOK_SECRET="whsec_example",
    PAYPAL_CLIENT_ID="test", PAYPAL_CLIENT_SECRET="test", PAYPAL_WEBHOOK_ID="test", PAYPAL_MODE="sandbox",
    PAYMENT_BASE_URL="https://g-fleet-iq-1.onrender.com",
    STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class PaymentTests(TestCase):
    def setUp(self):
        self.account = FleetAccount.objects.create(name="Merchant")
        self.company = Company.objects.create(account=self.account, name="Customer")
        self.user = get_user_model().objects.create_user(username="owner")
        AccountMembership.objects.create(user=self.user, account=self.account, role="owner")
        self.client.force_login(self.user)
        self.invoice = CompanyInvoice.objects.create(
            company=self.company, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
            due_date=date(2026, 11, 1), truck_count=2, trailer_count=3)

    def attempt(self, provider="stripe", **kwargs):
        return InvoicePayment.objects.create(invoice=self.invoice, provider=provider, amount=Decimal("105.00"),
                                             created_by=self.user, **kwargs)

    def stripe_session(self, payment, **extra):
        return {"id": payment.external_id or "cs_example", "mode": "payment", "livemode": False,
                "metadata": {"payment_id": str(payment.pk)}, "client_reference_id": str(self.invoice.pk),
                "payment_status": "paid", "status": "complete", "amount_total": 10500,
                "currency": "usd", "payment_intent": "pi_example", **extra}

    def paypal_order(self, payment, **capture_extra):
        return {"id": payment.external_id, "status": "COMPLETED", "purchase_units": [{
            "custom_id": str(payment.pk), "payments": {"captures": [{"id": "cap_example", "status": "COMPLETED",
            "amount": {"value": "105.00", "currency_code": "USD"}, **capture_extra}]}}]}

    def signed_event(self, session, event_type="checkout.session.completed", timestamp=None):
        payload = json.dumps({"id": "evt_example", "type": event_type, "data": {"object": session}}).encode()
        timestamp = timestamp or int(time.time())
        signature = hmac.new(b"whsec_example", str(timestamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
        return self.client.post(reverse("stripe_webhook"), payload, content_type="application/json",
                                HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={signature}")

    @patch("dashboard.payments.stripe_call")
    def test_checkout_uses_server_total_and_reuses_pending_attempt(self, api):
        api.return_value = {"id": "cs_example", "url": "https://checkout.stripe.com/c/pay/example"}
        url = reverse("payment_start", args=[self.invoice.pk, "stripe"])
        response = self.client.post(url, {"amount": "0.01"})
        self.assertEqual(response.url, api.return_value["url"])
        payment = InvoicePayment.objects.get()
        self.assertEqual(payment.amount, Decimal("105.00"))
        self.assertEqual(api.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"], 10500)
        self.assertEqual(api.call_args.kwargs["idempotency_key"], str(payment.pk))
        api.return_value = self.stripe_session(payment, payment_status="unpaid", status="open")
        self.assertEqual(self.client.post(url).url, payment.checkout_url)
        self.assertEqual(InvoicePayment.objects.count(), 1)
        self.assertEqual(api.call_count, 2)

    @patch("dashboard.payments.stripe_call")
    def test_creation_timeout_persists_attempt_and_reuses_idempotency_key(self, api):
        api.side_effect = payments.PaymentError("Temporary failure")
        url = reverse("payment_start", args=[self.invoice.pk, "stripe"])
        self.client.post(url)
        payment = InvoicePayment.objects.get()
        api.side_effect = None
        api.return_value = {"id": "cs_example", "url": "https://checkout.stripe.com/c/pay/example"}
        self.client.post(url)
        self.assertEqual(InvoicePayment.objects.count(), 1)
        self.assertTrue(all(call.kwargs["idempotency_key"] == str(payment.pk) for call in api.call_args_list))

    def test_signed_webhook_is_public_and_idempotent(self):
        payment = self.attempt(external_id="cs_example")
        self.client.logout()
        self.assertEqual(self.signed_event(self.stripe_session(payment)).status_code, 200)
        self.invoice.refresh_from_db()
        timestamp = self.invoice.paid_at
        self.assertEqual(self.invoice.status, "paid")
        self.assertEqual(self.invoice.paid_by, self.user)
        self.assertEqual(self.invoice.amount_due, 0)
        self.assertEqual(self.signed_event(self.stripe_session(payment)).status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_at, timestamp)
        payment.refresh_from_db()
        self.assertEqual(payment.reference, "pi_example")

    def test_webhook_rejects_invalid_signature_and_old_timestamp(self):
        payment = self.attempt(external_id="cs_example")
        self.client.logout()
        self.assertEqual(self.client.post(reverse("stripe_webhook"), "{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.signed_event(self.stripe_session(payment), timestamp=int(time.time()) - 600).status_code, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")

    def test_paid_webhook_rejects_wrong_amount_currency_or_invoice(self):
        payment = self.attempt(external_id="cs_example")
        for extra in ({"amount_total": 1}, {"currency": "eur"}, {"client_reference_id": "999"}, {"id": "cs_wrong"}, {"livemode": True}):
            with self.subTest(extra=extra):
                self.assertEqual(self.signed_event(self.stripe_session(payment, **extra)).status_code, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")

    def test_unpaid_event_does_not_settle_and_expiry_allows_new_checkout(self):
        payment = self.attempt(external_id="cs_example")
        session = self.stripe_session(payment, payment_status="unpaid", status="open")
        self.assertEqual(self.signed_event(session).status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")
        self.signed_event({**session, "status": "expired"}, "checkout.session.expired")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "cancelled")

    @patch("dashboard.payments.stripe_call")
    def test_success_return_verifies_provider_instead_of_trusting_query(self, api):
        payment = self.attempt(external_id="cs_example")
        api.return_value = self.stripe_session(payment, payment_status="unpaid", status="open")
        self.client.get(reverse("payment_return", args=[payment.pk]) + "?paid=true")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")

    @patch("dashboard.payments.paypal_request")
    def test_paypal_create_and_post_capture(self, api):
        api.return_value = {"id": "order_example", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=order_example"}]}
        response = self.client.post(reverse("payment_start", args=[self.invoice.pk, "paypal"]))
        self.assertIn("sandbox.paypal.com", response.url)
        payment = InvoicePayment.objects.get()
        self.assertEqual(api.call_args.kwargs["payload"]["purchase_units"][0]["amount"]["value"], "105.00")
        api.return_value = {"id": payment.external_id, "status": "APPROVED", "purchase_units": [{"custom_id": str(payment.pk)}]}
        self.assertContains(self.client.get(reverse("payment_return", args=[payment.pk])), "Complete PayPal payment")
        self.assertNotIn("/capture", api.call_args.args[0])
        api.return_value = self.paypal_order(payment)
        self.client.post(reverse("payment_return", args=[payment.pk]))
        self.assertTrue(api.call_args.args[0].endswith("/capture"))
        self.assertEqual(api.call_args.kwargs["request_id"], "capture-" + str(payment.pk))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")

    @patch("dashboard.payments.paypal_request")
    def test_declined_paypal_capture_does_not_pay_invoice(self, api):
        payment = self.attempt(provider="paypal", external_id="order_example")
        api.return_value = self.paypal_order(payment, status="DECLINED")
        self.client.post(reverse("payment_return", args=[payment.pk]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")

    @patch("dashboard.payments.verify_paypal_webhook")
    @patch("dashboard.payments.paypal_request")
    def test_paypal_webhook_rejects_forgery_and_reconciles_verified_payment(self, api, verify):
        payment = self.attempt(provider="paypal", external_id="order_example")
        event = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
            "supplementary_data": {"related_ids": {"order_id": payment.external_id}}}}
        self.client.logout()
        verify.return_value = False
        self.assertEqual(self.client.post(reverse("paypal_webhook"), event, content_type="application/json").status_code, 400)
        api.assert_not_called()
        verify.return_value = True
        api.return_value = self.paypal_order(payment)
        self.assertEqual(self.client.post(reverse("paypal_webhook"), event, content_type="application/json").status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")

    def test_client_admin_can_pay_but_viewer_and_dispatcher_cannot(self):
        for role in ("client_admin", "viewer", "dispatcher"):
            user = get_user_model().objects.create_user(username=role)
            CompanyMembership.objects.create(user=user, company=self.company, role=role)
            self.client.force_login(user)
            with patch("dashboard.payments.create_checkout", return_value="https://checkout.stripe.com/c/pay/test"):
                response = self.client.post(reverse("payment_start", args=[self.invoice.pk, "stripe"]))
            self.assertEqual(response.status_code, {"client_admin": 302, "viewer": 403, "dispatcher": 404}[role])

    def test_other_account_cannot_pay_or_capture(self):
        other = FleetAccount.objects.create(name="Other")
        company = Company.objects.create(account=other, name="Private")
        self.invoice.company = company
        self.invoice.save()
        payment = self.attempt()
        self.assertEqual(self.client.post(reverse("payment_start", args=[self.invoice.pk, "stripe"])).status_code, 404)
        self.assertEqual(self.client.post(reverse("payment_return", args=[payment.pk])).status_code, 404)

    def test_pending_and_review_payments_block_manual_marking_and_second_provider(self):
        payment = self.attempt()
        self.client.post(reverse("invoice_detail", args=[self.invoice.pk]), {"action": "mark_paid"})
        response = self.client.post(reverse("payment_start", args=[self.invoice.pk, "paypal"]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(InvoicePayment.objects.count(), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "issued")
        payment.status = "review"
        payment.save()
        self.client.post(reverse("payment_start", args=[self.invoice.pk, "stripe"]))
        self.assertEqual(InvoicePayment.objects.count(), 1)

    @override_settings(STRIPE_WEBHOOK_SECRET="")
    def test_incomplete_configuration_hides_button_and_blocks_checkout(self):
        self.assertNotContains(self.client.get(reverse("invoice_detail", args=[self.invoice.pk])), "Pay by card")
        self.client.post(reverse("payment_start", args=[self.invoice.pk, "stripe"]))
        self.assertFalse(InvoicePayment.objects.exists())

    @patch("dashboard.payments.stripe_call")
    def test_stripe_cancel_expires_checkout_before_unlocking_invoice(self, api):
        payment = self.attempt(external_id="cs_example")
        api.side_effect = [self.stripe_session(payment, payment_status="unpaid", status="open"), {"status": "expired"}]
        url = reverse("payment_cancel", args=[payment.pk])
        self.client.get(url)
        api.assert_not_called()
        self.client.post(url)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "cancelled")
        self.assertEqual(api.call_count, 2)

    def test_one_pending_attempt_enforced_by_database(self):
        self.attempt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.attempt(provider="paypal")

    def test_cancelled_paypal_order_cannot_be_captured_from_old_tab(self):
        payment = self.attempt(provider="paypal", external_id="order_example", status="cancelled")
        with patch("dashboard.payments.paypal_request") as api:
            self.client.post(reverse("payment_return", args=[payment.pk]))
        api.assert_not_called()

    def test_paid_void_and_zero_invoices_cannot_start_checkout(self):
        for status, count in (("paid", 2), ("void", 2), ("issued", 0)):
            self.invoice.status, self.invoice.truck_count, self.invoice.trailer_count = status, count, 0
            self.invoice.save()
            self.client.post(reverse("payment_start", args=[self.invoice.pk, "stripe"]))
            self.assertFalse(InvoicePayment.objects.exists())

    def test_checkout_redirect_rejects_untrusted_hosts(self):
        for url in ("http://checkout.stripe.com/test", "https://checkout.stripe.com.evil.test/test", "https://example.com"):
            with self.assertRaises(payments.PaymentError):
                payments.safe_checkout_url("stripe", url)

    def test_late_payment_for_void_invoice_is_kept_for_review(self):
        payment = self.attempt(external_id="cs_example")
        self.invoice.status = "void"
        self.invoice.save()
        self.signed_event(self.stripe_session(payment))
        self.invoice.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.invoice.status, "void")
        self.assertEqual(payment.status, "review")
        self.assertEqual(payment.reference, "pi_example")

    def test_stripe_sdk_transport_create_retrieve_and_expire(self):
        payment = self.attempt()
        session = self.stripe_session(payment, payment_status="unpaid", status="open",
                                      url="https://checkout.stripe.com/c/pay/example")
        with patch.object(stripe.default_http_client, "request", return_value=(json.dumps(session), 200, {})) as transport:
            self.assertEqual(payments.create_checkout(payment), session["url"])
            method, url, headers, body = transport.call_args.args
            self.assertEqual(method, "post")
            self.assertTrue(url.endswith("/v1/checkout/sessions"))
            self.assertEqual(headers["Idempotency-Key"], str(payment.pk))
            self.assertEqual(parse_qs(body)["line_items[0][price_data][unit_amount]"], ["10500"])
            payments.refresh_payment(payment)
            self.assertEqual(transport.call_args.args[0], "get")
            payments.stripe_call(stripe.checkout.Session.expire, payment.external_id)
            self.assertTrue(transport.call_args.args[1].endswith("/expire"))

    def test_paypal_webhook_verification_uses_registered_id_and_headers(self):
        from django.test import RequestFactory
        request = RequestFactory().post("/", HTTP_PAYPAL_TRANSMISSION_ID="transmission",
                                       HTTP_PAYPAL_TRANSMISSION_SIG="signature")
        with patch("dashboard.payments.paypal_request", return_value={"verification_status": "SUCCESS"}) as api:
            self.assertTrue(payments.verify_paypal_webhook(request, {"id": "event"}))
        payload = api.call_args.kwargs["payload"]
        self.assertEqual(payload["webhook_id"], "test")
        self.assertEqual(payload["transmission_sig"], "signature")
