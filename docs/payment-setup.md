# Invoice payments

G Fleet IQ accepts one-time USD invoice payments through hosted Stripe card checkout
and PayPal checkout. It does not create automatic subscriptions. Only the account
administrator or the billed company's client administrator can initiate payment.
Invoice totals come from the stored monthly truck/trailer snapshot.

The integration stays unavailable until its credentials AND webhook settings exist.
Put all credentials in Render's Environment tab, never in GitHub or chat.

## Stripe

- `STRIPE_SECRET_KEY`: the account's API secret key (live `sk_live_` or suitable restricted key).
- `STRIPE_WEBHOOK_SECRET`: the signing secret for this website's event destination (`whsec_`).
- Create a live snapshot-event webhook destination for this account at
  `https://g-fleet-iq-1.onrender.com/billing/webhooks/stripe/`.
- Subscribe to `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
  and `checkout.session.expired`.
- The hosted checkout does not require a publishable key in this application.

## PayPal

- Complete business-account verification, then create a live REST API merchant app.
- `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`: credentials from that live app.
- `PAYPAL_MODE=live` (default); use `sandbox` only in a separate test environment.
- Create a webhook in the same REST app at
  `https://g-fleet-iq-1.onrender.com/billing/webhooks/paypal/` for `PAYMENT.CAPTURE.COMPLETED`.
- `PAYPAL_WEBHOOK_ID`: the registered webhook's ID, not the client ID.
- After PayPal approval, the buyer returns and confirms payment with a CSRF-protected
  POST. The server captures the approved order and verifies the completed capture.

## Render and validation

- `PAYMENT_BASE_URL` defaults to `RENDER_EXTERNAL_URL`. Set it to the canonical HTTPS
  website URL when using a custom domain. Register webhooks separately for another service.
- Existing build command runs migrations; migration `0038_invoicepayment` stores attempts.
- Save environment changes and deploy them. Never mix live API keys with sandbox webhook secrets.
- Validate each provider in a separate sandbox deployment with its own database first.
  Check successful, failed, cancelled, repeated, and abandoned payments and webhook retries.
- A live transaction has NOT been validated merely because automated tests pass. Before
  launch, use an authorized real invoice to verify checkout, provider receipt, webhook
  delivery, paid status, and zero balance. Do not create arbitrary live charges for testing.

Attempts reuse the provider idempotency key. Only one checkout can be open per invoice.
To switch payment methods, close the existing checkout. Stripe sessions are expired
at Stripe before the invoice is unlocked; cancelled PayPal attempts cannot be captured
through an old browser tab. Manual payment recording is blocked while checkout is open.
The browser's success URL alone never marks an invoice paid.

If funds arrive after an invoice was changed or voided, the payment is retained as
`review`, the invoice is not automatically changed, and checkout is blocked. Reconcile
that receipt and any refunds in the provider dashboard before making an administrative
database correction. Refunds/disputes are not automatically applied to invoices.

Official references:
- https://docs.stripe.com/api/checkout/sessions/create
- https://docs.stripe.com/events/manage-webhook-endpoints
- https://developer.paypal.com/api/orders/v2
- https://developer.paypal.com/api/rest/webhooks/rest/
