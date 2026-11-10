# Freight marketplace

## Included

- `/marketplace/`: search direct postings across G Fleet IQ accounts. Only open, unexpired postings with a current or future pickup date appear.
- `/marketplace/post/`: account administrators and client administrators/dispatchers publish freight. Client users must choose a company they can manage.
- `/marketplace/?mine=1`: manage postings belonging to the current account or writable client companies, including expired and closed postings.
- `/marketplace/<id>/`: freight and poster-supplied contact details.
- POST `/marketplace/<id>/close/`: close an owned posting; it immediately disappears from other customers' searches and detail access.
- `/find-loads/`: separate search for existing private dispatch loads, with existing Profit Engine estimates.

Posting requires explicit confirmation that freight and contact details will be shared with all signed-in marketplace customers. Private dispatch loads are never copied or published automatically. Posters can close and replace a listing to correct details. Contacting a poster does not book or assign a load.

Accounts and users use existing registration and membership setup. This release does not include an anonymous broker submission form or independent verification of a business, freight, or contact. Descriptive broker/shipper labels are self-reported.

## Deployment

Run `python manage.py migrate` with the application deployment. Migration `fleet/0039_freight_posting.py` creates only the marketplace table and index; it does not change existing dispatch records. No provider credentials are required for direct postings. No production deployment has been performed as part of this change.

## External providers remain pending

DAT and Truckstop listings are not loaded, simulated, or scraped. Their integrations require provider access and agreements covering use by multiple G Fleet IQ customers. Do not use one customer's credentials to serve another customer.

- DAT API access: https://www.dat.com/api-integration
- Truckstop partner requirements: https://developer.truckstop.com/reference/general-overview

Confirm search rights, per-customer entitlements, authentication, data retention, and pricing with each provider before implementing a live adapter. Broker/shipper direct feeds require their own explicit authorization.

## Validation

`python manage.py test dashboard.test_marketplace dashboard.test_load_search`

Nine tests cover cross-account marketplace visibility, private load isolation, role permissions, forged ownership/company fields, publishing consent, date/weight/rate validation, closed/expired access, search filters, authentication, and CSRF.

Local validation used Python 3.12 and Django 5.2; repeat on the repository's pinned Python/Django 6 deployment runtime before release. Existing model primary-key warnings are unrelated to this feature.

## Load Sources directory

`/load-sources/` is available to all existing signed-in account and company members, including read-only users. It offers separate Sign in and Register links for DAT One, Truckstop, 123Loadboard, Direct Freight, C.H. Robinson/Navisphere Carrier, Uber Freight, RXO Connect, and TQL Carrier Dashboard. Links were checked against official provider pages on November 10, 2026. They open externally with noopener/noreferrer and do not send customer data or store credentials. Registration buttons open the provider signup, plan selection, or carrier onboarding entry point. Customers complete approval and subscriptions directly with the provider; the directory does not imply an API connection, automatic login, or coverage of all freight sources.
