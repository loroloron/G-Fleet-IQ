"""Server-side invoice checkout; credentials are read only from deployment settings."""
import base64
import json
import logging
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from fleet.models import CompanyInvoice, InvoicePayment


stripe.default_http_client = stripe.RequestsClient(timeout=15)
logger = logging.getLogger(__name__)


class PaymentError(Exception):
    pass


def configured(provider):
    if provider == "stripe":
        return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET)
    if provider == "paypal":
        return bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET
                    and settings.PAYPAL_WEBHOOK_ID and settings.PAYPAL_MODE in {"live", "sandbox"})
    return False


def stripe_call(operation, *args, **kwargs):
    try:
        result = operation(*args, api_key=settings.STRIPE_SECRET_KEY, **kwargs)
        return result.to_dict() if isinstance(result, stripe.StripeObject) else result
    except stripe.StripeError as exc:
        # Log only the exception category and status, never provider messages,
        # response bodies, request parameters, or credentials.
        logger.warning("Stripe request failed: category=%s status=%s",
                       type(exc).__name__, exc.http_status)
        if isinstance(exc, stripe.AuthenticationError):
            raise PaymentError("Stripe rejected the configured API key. Please contact your billing administrator.") from exc
        if isinstance(exc, stripe.PermissionError):
            raise PaymentError("The Stripe API key does not allow this payment request. Please contact your billing administrator.") from exc
        raise PaymentError("Stripe could not complete this request. Please try again.") from exc


def paypal_request(path, *, payload=None, request_id=None):
    base = ("https://api-m.paypal.com" if settings.PAYPAL_MODE == "live"
            else "https://api-m.sandbox.paypal.com")
    credentials = base64.b64encode(
        f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}".encode()
    ).decode()
    try:
        auth = Request(base + "/v1/oauth2/token", data=b"grant_type=client_credentials",
                       headers={"Authorization": "Basic " + credentials,
                                "Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(auth, timeout=15) as response:
            token = json.load(response)["access_token"]
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        request = Request(base + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        raise PaymentError("PayPal could not complete this request. Please try again.") from exc


def callback_url(payment, action):
    from django.urls import reverse
    return settings.PAYMENT_BASE_URL.rstrip("/") + reverse(action, args=[payment.pk])


def safe_checkout_url(provider, url):
    parsed = urlparse(url)
    hosts = {"checkout.stripe.com"} if provider == "stripe" else {
        "www.paypal.com", "www.sandbox.paypal.com"}
    if parsed.scheme != "https" or parsed.hostname not in hosts:
        raise PaymentError("The payment provider did not return a valid checkout link.")
    return url


def create_checkout(payment):
    # Every retry for this attempt uses the same provider idempotency key and data.
    if payment.provider == "stripe":
        session = stripe_call(
            stripe.checkout.Session.create, mode="payment", payment_method_types=["card"],
            client_reference_id=str(payment.invoice_id), metadata={"payment_id": str(payment.pk)},
            line_items=[{"price_data": {"currency": "usd", "unit_amount": int(payment.amount * 100),
                         "product_data": {"name": payment.invoice.invoice_number}}, "quantity": 1}],
            success_url=callback_url(payment, "payment_return"),
            cancel_url=callback_url(payment, "payment_cancel"),
            idempotency_key=str(payment.pk),
        )
        external_id, url = session["id"], session["url"]
    else:
        order = paypal_request("/v2/checkout/orders", payload={
            "intent": "CAPTURE",
            "purchase_units": [{"custom_id": str(payment.pk),
                                "description": payment.invoice.invoice_number,
                                "amount": {"currency_code": "USD", "value": str(payment.amount)}}],
            "payment_source": {"paypal": {"experience_context": {
                "brand_name": "G Fleet IQ", "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW", "return_url": callback_url(payment, "payment_return"),
                "cancel_url": callback_url(payment, "payment_cancel")}}},
        }, request_id=str(payment.pk))
        external_id = order["id"]
        url = next((link["href"] for link in order.get("links", [])
                    if link["rel"] in {"payer-action", "approve"}), "")
    payment.external_id = external_id
    payment.checkout_url = safe_checkout_url(payment.provider, url)
    payment.save(update_fields=["external_id", "checkout_url"])
    return payment.checkout_url


def settle(payment, amount, currency, reference):
    try:
        amount = Decimal(str(amount))
    except InvalidOperation as exc:
        raise PaymentError("The provider returned an invalid payment amount.") from exc
    if amount != payment.amount or currency.lower() != "usd" or not reference:
        raise PaymentError("The payment amount or currency does not match this invoice.")
    # Always lock invoice before payment (also used by checkout and manual recording).
    with transaction.atomic():
        invoice = CompanyInvoice.objects.select_for_update().get(pk=payment.invoice_id)
        locked = InvoicePayment.objects.select_for_update().get(pk=payment.pk)
        if locked.status == "succeeded":
            return
        locked.reference = reference
        locked.completed_at = timezone.now()
        if invoice.status != "issued" or invoice.total != locked.amount:
            # Preserve funds received even if someone changed the invoice outside this flow.
            locked.status = "review"
        else:
            locked.status = "succeeded"
            invoice.status, invoice.paid_at, invoice.paid_by = "paid", locked.completed_at, locked.created_by
            invoice.save(update_fields=["status", "paid_at", "paid_by"])
        locked.save(update_fields=["reference", "status", "completed_at"])


def reconcile_stripe(payment, session=None):
    if session is None:
        session = stripe_call(stripe.checkout.Session.retrieve, payment.external_id)
    if (session.get("livemode") != settings.STRIPE_SECRET_KEY.startswith(("sk_live_", "rk_live_"))
            or session.get("metadata", {}).get("payment_id") != str(payment.pk)
            or session.get("client_reference_id") != str(payment.invoice_id)
            or (payment.external_id and session["id"] != payment.external_id)
            or session.get("mode") != "payment"):
        raise PaymentError("The checkout does not match this invoice.")
    if not payment.external_id:
        # A signed webhook can recover a checkout whose creation response timed out.
        payment.external_id = session["id"]
        payment.save(update_fields=["external_id"])
    if session.get("payment_status") == "paid":
        settle(payment, Decimal(session["amount_total"]) / 100, session["currency"],
               session.get("payment_intent"))
    elif session.get("status") == "expired":
        InvoicePayment.objects.filter(pk=payment.pk, status="pending").update(status="cancelled")


def reconcile_paypal(payment, order):
    units = order.get("purchase_units", [])
    if (order.get("id") != payment.external_id or len(units) != 1
            or units[0].get("custom_id") != str(payment.pk)):
        raise PaymentError("The PayPal order does not match this invoice.")
    captures = units[0].get("payments", {}).get("captures", [])
    if order.get("status") == "COMPLETED" and len(captures) == 1:
        capture = captures[0]
        if capture.get("status") == "COMPLETED":
            settle(payment, capture["amount"]["value"], capture["amount"]["currency_code"], capture["id"])
    elif order.get("status") == "VOIDED":
        InvoicePayment.objects.filter(pk=payment.pk, status="pending").update(status="cancelled")


def refresh_payment(payment):
    if payment.provider == "stripe":
        reconcile_stripe(payment)
    else:
        reconcile_paypal(payment, paypal_request("/v2/checkout/orders/" + quote(payment.external_id)))
    payment.refresh_from_db()


def verify_paypal_webhook(request, event):
    headers = request.headers
    result = paypal_request("/v1/notifications/verify-webhook-signature", payload={
        "auth_algo": headers.get("Paypal-Auth-Algo", ""),
        "cert_url": headers.get("Paypal-Cert-Url", ""),
        "transmission_id": headers.get("Paypal-Transmission-Id", ""),
        "transmission_sig": headers.get("Paypal-Transmission-Sig", ""),
        "transmission_time": headers.get("Paypal-Transmission-Time", ""),
        "webhook_id": settings.PAYPAL_WEBHOOK_ID, "webhook_event": event,
    })
    return result.get("verification_status") == "SUCCESS"
