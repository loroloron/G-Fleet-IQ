import json
from urllib.parse import quote

import stripe
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from fleet.models import CompanyInvoice, CompanyMembership, InvoicePayment
from . import payments


def payable_invoices(request):
    invoices = CompanyInvoice.objects.filter(company__account=request.account)
    if not request.is_account_admin:
        admin_ids = {m.company_id for m in request.company_memberships
                     if m.role == CompanyMembership.ROLE_CLIENT_ADMIN}
        invoices = invoices.filter(company_id__in=admin_ids)
    return invoices


def invoice_redirect(payment):
    return redirect("invoice_detail", invoice_id=payment.invoice_id)


@require_POST
def payment_start(request, invoice_id, provider):
    invoice = get_object_or_404(payable_invoices(request), pk=invoice_id)
    if not payments.configured(provider):
        messages.error(request, "This payment method is not available yet.")
        return redirect("invoice_detail", invoice_id=invoice.pk)
    try:
        with transaction.atomic():
            invoice = CompanyInvoice.objects.select_for_update().get(pk=invoice.pk)
            if invoice.status != "issued" or invoice.total <= 0:
                raise payments.PaymentError("No payment is due on this invoice.")
            if invoice.payments.filter(status="review").exists():
                raise payments.PaymentError("Payment already received and awaiting review. Do not pay again.")
            payment = invoice.payments.filter(status="pending").first()
            if payment and payment.external_id:
                payments.refresh_payment(payment)
                invoice.refresh_from_db()
                if invoice.status != "issued":
                    return redirect("invoice_detail", invoice_id=invoice.pk)
                if payment.status != "pending":
                    payment = None
            if payment and payment.provider != provider:
                raise payments.PaymentError("A checkout is already open. Cancel it before choosing another payment method.")
            if payment is None:
                payment = InvoicePayment.objects.create(
                    invoice=invoice, provider=provider, amount=invoice.total, created_by=request.user)
            url = payment.checkout_url
        # Persist the attempt before the network call: a timeout retry must reuse its key.
        if not url:
            url = payments.create_checkout(payment)
        return redirect(payments.safe_checkout_url(provider, url))
    except payments.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect("invoice_detail", invoice_id=invoice.pk)


@require_http_methods(["GET", "POST"])
def payment_return(request, payment_id):
    payment = get_object_or_404(InvoicePayment, pk=payment_id, invoice__in=payable_invoices(request))
    try:
        if payment.status == "pending" and payment.external_id:
            if payment.provider == "paypal" and request.method == "POST":
                with transaction.atomic():
                    invoice = CompanyInvoice.objects.select_for_update().get(pk=payment.invoice_id)
                    payment.refresh_from_db()
                    if payment.status == "pending" and invoice.status == "issued":
                        order = payments.paypal_request(
                            "/v2/checkout/orders/" + quote(payment.external_id) + "/capture",
                            payload={}, request_id="capture-" + str(payment.pk))
                        payments.reconcile_paypal(payment, order)
            else:
                payments.refresh_payment(payment)
        payment.refresh_from_db()
        if payment.status == "pending" and payment.provider == "paypal":
            return render(request, "dashboard/payment_confirm.html", {"payment": payment})
        if payment.status == "succeeded":
            messages.success(request, "Payment confirmed. Your invoice is paid.")
        elif payment.status == "review":
            messages.warning(request, "Payment received and awaiting invoice review. Do not pay again; contact G Fleet IQ.")
        else:
            messages.info(request, "Payment has not been confirmed yet. Your invoice remains unpaid.")
    except payments.PaymentError as exc:
        messages.error(request, str(exc))
    return invoice_redirect(payment)


@require_http_methods(["GET", "POST"])
def payment_cancel(request, payment_id):
    payment = get_object_or_404(InvoicePayment, pk=payment_id, invoice__in=payable_invoices(request))
    if request.method == "GET":
        return render(request, "dashboard/payment_confirm.html", {"payment": payment, "cancel": True})
    try:
        with transaction.atomic():
            CompanyInvoice.objects.select_for_update().get(pk=payment.invoice_id)
            payment.refresh_from_db()
            if payment.status == "pending":
                if not payment.external_id:
                    raise payments.PaymentError("Checkout setup is incomplete. Retry the original payment method before cancelling.")
                payments.refresh_payment(payment)
                if payment.status == "pending" and payment.provider == "stripe":
                    session = payments.stripe_call(stripe.checkout.Session.expire, payment.external_id)
                    if session.get("status") != "expired":
                        raise payments.PaymentError("The checkout could not be cancelled. Please try again.")
                if payment.status == "pending":
                    payment.status = "cancelled"
                    payment.save(update_fields=["status"])
        messages.info(request, "Checkout closed. Check your invoice for its current payment status.")
    except payments.PaymentError as exc:
        messages.error(request, str(exc))
    return invoice_redirect(payment)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not payments.configured("stripe"):
        return HttpResponse(status=503)
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.headers.get("Stripe-Signature", ""), settings.STRIPE_WEBHOOK_SECRET)
        event = event.to_dict()
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)
    if event["type"] not in {"checkout.session.completed", "checkout.session.async_payment_succeeded",
                              "checkout.session.expired"}:
        return HttpResponse(status=200)
    session = event["data"]["object"]
    try:
        payment = InvoicePayment.objects.filter(
            pk=session.get("metadata", {}).get("payment_id"), provider="stripe").first()
        if payment:
            payments.reconcile_stripe(payment, session)
    except (ValueError, ValidationError, payments.PaymentError):
        return HttpResponse(status=400)
    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def paypal_webhook(request):
    if not payments.configured("paypal"):
        return HttpResponse(status=503)
    try:
        event = json.loads(request.body)
        if not isinstance(event, dict) or not payments.verify_paypal_webhook(request, event):
            return HttpResponse(status=400)
        if event.get("event_type") == "PAYMENT.CAPTURE.COMPLETED":
            order_id = event.get("resource", {}).get("supplementary_data", {}).get("related_ids", {}).get("order_id")
            if order_id:
                payment = InvoicePayment.objects.filter(provider="paypal", external_id=order_id).first()
                if payment:
                    # Fetch using this merchant's credentials instead of trusting payer-supplied data.
                    payments.refresh_payment(payment)
    except (ValueError, TypeError):
        return HttpResponse(status=400)
    except payments.PaymentError:
        return HttpResponse(status=503)
    return HttpResponse(status=200)
