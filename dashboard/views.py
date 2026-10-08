from datetime import date, datetime, time, timedelta
import calendar
import secrets
import hmac

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Avg, Sum, Q
from django.utils import timezone

from fleet.models import (
    Company,
    FleetAccount,
    AccountMembership,
    CompanyMembership,
    Customer,
    Driver,
    DriverDutyLog,
    Truck,
    Trailer,
    Load,
    SamsaraConnection,
    CompanyInvoice,
)

from .payments import configured as payment_configured

from .samsara import (
    SamsaraError,
    authorization_url as samsara_authorization_url,
    encrypt_token as encrypt_samsara_token,
    exchange_code as exchange_samsara_code,
    oauth_is_configured as samsara_oauth_is_configured,
    token_expiry as samsara_token_expiry,
)

from .forms import (
    CompanyForm,
    CustomerForm,
    DriverForm,
    TruckForm,
    TrailerForm,
    LoadForm,
)

from .fuel_engine import find_best_fuel_stop

from .ai_engine import (
    select_best_driver,
    select_best_truck,
    select_best_trailer,
)
from .profit_engine import (
    calculate_load_profit,
    save_load_profit,
)

from .geocode_engine import geocode_address
from .planning_engine import plan_all_loads as build_plans
from .planning_engine import calculate_driver_distance
from .route_engine import calculate_route
from .profit_engine import (
    calculate_load_profit,
     
)
def landing(request):
    return render(request, "dashboard/landing.html")


def _samsara_manageable_companies(request):
    companies = Company.objects.filter(account=request.account, active=True)
    if request.is_account_admin:
        return companies.order_by("name")
    return companies.filter(
        memberships__user=request.user,
        memberships__active=True,
        memberships__role=CompanyMembership.ROLE_CLIENT_ADMIN,
    ).distinct().order_by("name")


def _samsara_company_redirect(company_id=None):
    url = reverse("samsara_integration")
    return redirect(f"{url}?company_id={company_id}" if company_id else url)


def samsara_integration(request):
    companies = _samsara_manageable_companies(request)
    if not companies.exists():
        return HttpResponseForbidden("Only a G-Fleet-IQ administrator or client company administrator can connect Samsara.")
    company_id = request.GET.get("company_id")
    if company_id:
        company = companies.filter(pk=company_id).first()
        if not company:
            return HttpResponseForbidden("You do not have access to that client company.")
    else:
        company = companies.first() if companies.count() == 1 else None
    connection = SamsaraConnection.objects.filter(company=company).first() if company else None
    return render(request, "dashboard/samsara.html", {
        "companies": companies,
        "selected_company": company,
        "connection": connection,
        "samsara_configured": samsara_oauth_is_configured(),
    })


def samsara_connect(request):
    if request.method != "POST":
        return HttpResponseForbidden("Use the connect button to start authorization.")
    companies = _samsara_manageable_companies(request)
    company = companies.filter(pk=request.POST.get("company_id", "")).first()
    if not company:
        return HttpResponseForbidden("Choose a client company you are allowed to manage.")
    if not samsara_oauth_is_configured():
        messages.error(request, "Samsara connection setup is not finished yet. The app credentials need to be added to the secure server settings.")
        return _samsara_company_redirect(company.pk)

    state = secrets.token_urlsafe(32)
    request.session["samsara_oauth_state"] = state
    request.session["samsara_oauth_account_id"] = request.account.pk
    request.session["samsara_oauth_user_id"] = request.user.pk
    request.session["samsara_oauth_company_id"] = company.pk
    return redirect(samsara_authorization_url(state))


def samsara_callback(request):
    expected_state = request.session.pop("samsara_oauth_state", "")
    account_id = request.session.pop("samsara_oauth_account_id", None)
    user_id = request.session.pop("samsara_oauth_user_id", None)
    company_id = request.session.pop("samsara_oauth_company_id", None)
    returned_state = request.GET.get("state", "")
    if not expected_state or not returned_state or not hmac.compare_digest(expected_state, returned_state):
        messages.error(request, "Samsara connection could not be verified. Please start again.")
        return redirect("samsara_integration")
    if not request.user.is_authenticated or user_id != request.user.pk or account_id != getattr(request.account, "pk", None):
        messages.error(request, "The company account changed during Samsara authorization. Please start again.")
        return redirect("samsara_integration")
    company = _samsara_manageable_companies(request).filter(pk=company_id).first()
    if not company:
        return HttpResponseForbidden("You no longer have access to the client company for this Samsara connection.")
    if request.GET.get("error"):
        messages.error(request, "Samsara authorization was cancelled or declined. You can try again.")
        return _samsara_company_redirect(company.pk)

    code = request.GET.get("code", "")
    if not code:
        messages.error(request, "Samsara did not return an authorization code. Please try again.")
        return _samsara_company_redirect(company.pk)
    try:
        token_data = exchange_samsara_code(code)
        SamsaraConnection.objects.update_or_create(
            company=company,
            defaults={
                "organization_name": "Samsara organization",
                "access_token_encrypted": encrypt_samsara_token(token_data["access_token"]),
                "refresh_token_encrypted": encrypt_samsara_token(token_data["refresh_token"]),
                "access_token_expires_at": samsara_token_expiry(token_data),
                "scopes": request.GET.get("scope", "")[:500],
                "connected_by": request.user,
            },
        )
    except SamsaraError as exc:
        messages.error(request, str(exc))
        return _samsara_company_redirect(company.pk)

    messages.success(request, f"Samsara is connected for {company.name}.")
    return _samsara_company_redirect(company.pk)


def _scope_queryset(request, model, writable=None):
    queryset = model.objects.filter(account=request.account)
    if request.is_account_admin:
        return queryset
    if writable is None:
        writable = request.method == "POST"
    company_ids = request.write_company_ids if writable else request.allowed_company_ids
    if model is Company:
        return queryset.filter(id__in=company_ids)
    if model is Load:
        return queryset.filter(company_id__in=company_ids)
    return queryset.filter(company_id__in=company_ids)


def _form_company_ids(request):
    if request.is_account_admin:
        return None
    return request.write_company_ids if request.method == "POST" else request.allowed_company_ids


def billing(request):
    companies = Company.objects.filter(account=request.account, active=True).order_by("name")
    invoices = CompanyInvoice.objects.filter(company__account=request.account).select_related("company")
    if not request.is_account_admin:
        companies = companies.filter(pk__in=request.allowed_company_ids)
        invoices = invoices.filter(company_id__in=request.allowed_company_ids)

    if request.method == "POST":
        if not request.is_account_admin:
            return HttpResponseForbidden("Only a G-Fleet-IQ account administrator can create invoices.")
        try:
            company_id = int(request.POST.get("company_id", ""))
        except (TypeError, ValueError):
            messages.error(request, "Choose a valid customer company before creating an invoice.")
            return redirect("billing")
        company = get_object_or_404(companies, pk=company_id)
        today = timezone.localdate()
        period_start = today.replace(day=1)
        period_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        truck_count = Truck.objects.filter(account=request.account, company=company, active=True).count()
        trailer_count = Trailer.objects.filter(account=request.account, company=company).count()
        invoice, created = CompanyInvoice.objects.get_or_create(
            company=company,
            period_start=period_start,
            period_end=period_end,
            defaults={
                "due_date": today + timedelta(days=30),
                "truck_count": truck_count,
                "trailer_count": trailer_count,
                "created_by": request.user,
            },
        )
        if created:
            messages.success(request, f"Invoice {invoice.invoice_number} created for {company.name}.")
        else:
            messages.info(request, f"An invoice already exists for {company.name} for this month.")
        return redirect("invoice_detail", invoice_id=invoice.pk)

    return render(request, "dashboard/billing.html", {
        "companies": companies,
        "invoices": invoices,
        "can_create_invoices": request.is_account_admin,
    })


def invoice_detail(request, invoice_id):
    invoices = CompanyInvoice.objects.filter(company__account=request.account).select_related("company")
    if not request.is_account_admin:
        invoices = invoices.filter(company_id__in=request.allowed_company_ids)
    invoice = get_object_or_404(invoices, pk=invoice_id)

    if request.method == "POST":
        if not request.is_account_admin:
            return HttpResponseForbidden("Only a G-Fleet-IQ account administrator can update invoice status.")
        action = request.POST.get("action")
        if action == "mark_paid":
            with transaction.atomic():
                locked = CompanyInvoice.objects.select_for_update().get(pk=invoice.pk)
                if locked.payments.filter(status__in=["pending", "review"]).exists():
                    messages.error(request, "Resolve the open checkout before recording a manual payment.")
                    return redirect("invoice_detail", invoice_id=invoice.pk)
                updated = invoices.filter(pk=invoice.pk, status=CompanyInvoice.STATUS_ISSUED).update(
                    status=CompanyInvoice.STATUS_PAID,
                    paid_at=timezone.now(),
                    paid_by=request.user,
                )
            if updated:
                messages.success(request, "Invoice marked as paid.")
            else:
                messages.info(request, "This invoice is already paid or void; its payment record was not changed.")
        return redirect("invoice_detail", invoice_id=invoice.pk)

    return render(request, "dashboard/invoice_detail.html", {
        "invoice": invoice,
        "can_manage_invoices": request.is_account_admin,
        "can_pay_invoice": request.is_account_admin or any(
            m.company_id == invoice.company_id and m.role == CompanyMembership.ROLE_CLIENT_ADMIN
            for m in request.company_memberships),
        "stripe_available": payment_configured("stripe"),
        "paypal_available": payment_configured("paypal"),
        "pending_payment": invoice.payments.filter(status="pending").first(),
        "review_payment": invoice.payments.filter(status="review").first(),
        "confirmed_payment": invoice.payments.filter(status="succeeded").first(),
    })


def sign_up(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    for field in form.fields.values():
        field.widget.attrs["class"] = "form-control"
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your account is ready. Welcome to G Fleet IQ!")
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})


def account_setup(request):
    account = FleetAccount.objects.order_by("id").first()
    if account is None:
        account = FleetAccount.objects.create(name="G Fleet IQ Account")
    if AccountMembership.objects.filter(user=request.user, active=True).exists():
        return redirect("home")

    if request.method == "POST":
        with transaction.atomic():
            account = FleetAccount.objects.select_for_update().get(pk=account.pk)
            owner_exists = AccountMembership.objects.filter(
                account=account,
                active=True,
                role=AccountMembership.ROLE_OWNER,
            ).exists()
            if owner_exists:
                messages.info(request, "Ask your G Fleet IQ account owner to add your username to the team.")
            else:
                AccountMembership.objects.create(
                    user=request.user,
                    account=account,
                    role=AccountMembership.ROLE_OWNER,
                )
                messages.success(request, "Your G Fleet IQ account is set up. You are the account owner.")
                return redirect("home")

    return render(request, "registration/account_setup.html", {"account": account})


def account_team(request):
    User = get_user_model()
    if request.method == "POST":
        action = request.POST.get("action")
        membership_id = request.POST.get("membership_id")
        if action == "remove" and membership_id:
            membership = get_object_or_404(
                AccountMembership,
                pk=membership_id,
                account=request.account,
            )
            if membership.role == AccountMembership.ROLE_OWNER and AccountMembership.objects.filter(
                account=request.account,
                active=True,
                role=AccountMembership.ROLE_OWNER,
            ).count() <= 1:
                messages.error(request, "The account needs at least one owner.")
            elif membership.user_id == request.user.id:
                messages.error(request, "You cannot remove your own account access here.")
            else:
                membership.delete()
                messages.success(request, "Team access removed.")
            return redirect("account_team")

        username = request.POST.get("username", "").strip()
        role = request.POST.get("role", AccountMembership.ROLE_ADMIN)
        if role not in dict(AccountMembership.ROLE_CHOICES):
            role = AccountMembership.ROLE_ADMIN
        teammate = User.objects.filter(username__iexact=username).first()
        if not teammate:
            messages.error(request, "That username is not registered yet. Ask them to create an account first.")
        elif AccountMembership.objects.filter(
            account=request.account,
            active=True,
            role=AccountMembership.ROLE_OWNER,
        ).exists() is False:
            messages.error(request, "Set up an account owner before adding administrators.")
        else:
            current = AccountMembership.objects.filter(user=teammate, account=request.account).first()
            if current and current.role == AccountMembership.ROLE_OWNER and role != AccountMembership.ROLE_OWNER:
                owner_count = AccountMembership.objects.filter(
                    account=request.account,
                    active=True,
                    role=AccountMembership.ROLE_OWNER,
                ).count()
                if owner_count <= 1:
                    messages.error(request, "The account needs at least one owner.")
                    return redirect("account_team")
            AccountMembership.objects.update_or_create(
                user=teammate,
                account=request.account,
                defaults={"role": role, "active": True},
            )
            messages.success(request, f"{teammate.username} now has {dict(AccountMembership.ROLE_CHOICES)[role]} access.")
        return redirect("account_team")

    return render(request, "dashboard/account_team.html", {
        "memberships": AccountMembership.objects.filter(account=request.account, active=True).select_related("user").order_by("joined_at"),
        "roles": AccountMembership.ROLE_CHOICES,
    })


def client_team(request, company_id):
    User = get_user_model()
    company = get_object_or_404(Company, pk=company_id, account=request.account)
    is_account_admin = request.is_account_admin
    existing = CompanyMembership.objects.filter(company=company, active=True).select_related("user")

    if request.method == "POST":
        action = request.POST.get("action")
        membership_id = request.POST.get("membership_id")
        if action == "remove" and membership_id:
            membership = get_object_or_404(existing, pk=membership_id)
            if membership.user_id == request.user.id:
                messages.error(request, "You cannot remove your own client access here.")
            elif membership.role == CompanyMembership.ROLE_CLIENT_ADMIN and not is_account_admin:
                messages.error(request, "Only the G Fleet IQ owner or an administrator can remove a client administrator.")
            else:
                membership.delete()
                messages.success(request, "Client access removed.")
            return redirect("client_team", company_id=company.id)

        username = request.POST.get("username", "").strip()
        role = request.POST.get("role", CompanyMembership.ROLE_VIEWER)
        allowed_roles = dict(CompanyMembership.ROLE_CHOICES)
        if not is_account_admin:
            allowed_roles.pop(CompanyMembership.ROLE_CLIENT_ADMIN, None)
        teammate = User.objects.filter(username__iexact=username).first()
        current_membership = CompanyMembership.objects.filter(company=company, user=teammate).first() if teammate else None

        if not teammate:
            messages.error(request, "That username is not registered yet. Ask them to create an account first.")
        elif role not in allowed_roles:
            messages.error(request, "You do not have permission to grant that access level.")
        elif current_membership and current_membership.role == CompanyMembership.ROLE_CLIENT_ADMIN and not is_account_admin:
            messages.error(request, "Only the G Fleet IQ owner or an administrator can change a client administrator’s access.")
        else:
            CompanyMembership.objects.update_or_create(
                user=teammate,
                company=company,
                defaults={"role": role, "active": True},
            )
            messages.success(request, f"{teammate.username} now has {dict(CompanyMembership.ROLE_CHOICES)[role]} access for {company.name}.")
        return redirect("client_team", company_id=company.id)

    roles = CompanyMembership.ROLE_CHOICES if is_account_admin else [
        choice for choice in CompanyMembership.ROLE_CHOICES
        if choice[0] != CompanyMembership.ROLE_CLIENT_ADMIN
    ]
    return render(request, "dashboard/client_team.html", {
        "company": company,
        "memberships": existing.order_by("joined_at"),
        "roles": roles,
    })

def home(request):
    all_loads = list(_scope_queryset(request, Load))

    total_revenue = 0
    total_profit = 0

    for load in all_loads:
        result = calculate_load_profit(load)
        total_revenue += result["revenue"]
        total_profit += result["profit"]

    average_profit = (
        total_profit / len(all_loads)
        if all_loads
        else 0
    )

    context = {
        "drivers": _scope_queryset(request, Driver).count(),
        "trucks": _scope_queryset(request, Truck).count(),
        "trailers": _scope_queryset(request, Trailer).count(),
        "loads": _scope_queryset(request, Load).count(),
        "customers": _scope_queryset(request, Customer).count(),
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "average_profit": average_profit,
    }
    return render(request, "dashboard/home.html", context)


def driver_logs(request):
    requested_day = request.GET.get("date", "").strip()
    try:
        selected_day = date.fromisoformat(requested_day) if requested_day else timezone.localdate()
    except ValueError:
        selected_day = timezone.localdate()

    current_timezone = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(selected_day, time.min), current_timezone)
    day_end = day_start + timedelta(days=1)
    now = timezone.now()
    drivers = _scope_queryset(request, Driver).select_related("company", "truck").order_by("name")
    driver_list = list(drivers)
    daily_drivers = []

    def formatted_duration(seconds):
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m"

    for driver in driver_list:
        entries = []
        totals = {"off_duty": 0, "on_duty": 0, "driving": 0}
        logs = DriverDutyLog.objects.filter(
            account=request.account,
            driver=driver,
            started_at__lt=day_end,
        ).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=day_start)).order_by("started_at", "id")

        for log in logs:
            entry_start = max(log.started_at, day_start)
            entry_end = min(log.ended_at or now, day_end, now)
            seconds = max(0, int((entry_end - entry_start).total_seconds()))
            totals[log.status] = totals.get(log.status, 0) + seconds
            entries.append({
                "status": log.get_status_display(),
                "source": log.get_source_display(),
                "automatic": log.source == DriverDutyLog.SOURCE_AUTOMATIC,
                "start": entry_start,
                "end": entry_end if log.ended_at or selected_day < timezone.localdate() else None,
                "seconds": seconds,
                "active": log.ended_at is None and selected_day == timezone.localdate(),
                "duration": formatted_duration(seconds),
            })

        daily_drivers.append({
            "driver": driver,
            "entries": entries,
            "off_duty": formatted_duration(totals["off_duty"]),
            "on_duty": formatted_duration(totals["on_duty"]),
            "driving": formatted_duration(totals["driving"]),
            "worked": formatted_duration(totals["on_duty"] + totals["driving"]),
        })

    stop_events = []
    loads_with_stops = _scope_queryset(request, Load).filter(driver__in=driver_list).filter(
        Q(pickup_arrived_at__gte=day_start, pickup_arrived_at__lt=day_end)
        | Q(pickup_departed_at__gte=day_start, pickup_departed_at__lt=day_end)
        | Q(delivery_arrived_at__gte=day_start, delivery_arrived_at__lt=day_end)
        | Q(delivery_departed_at__gte=day_start, delivery_departed_at__lt=day_end)
    ).select_related("driver", "customer")
    for load in loads_with_stops:
        for field, label, location in (
            ("pickup_arrived_at", "Arrived at pickup", load.pickup),
            ("pickup_departed_at", "Departed pickup", load.pickup),
            ("delivery_arrived_at", "Arrived at delivery", load.delivery),
            ("delivery_departed_at", "Departed delivery", load.delivery),
        ):
            occurred_at = getattr(load, field)
            if occurred_at and day_start <= occurred_at < day_end:
                stop_events.append({
                    "driver": load.driver.name if load.driver_id else "—",
                    "customer": load.customer.name,
                    "label": label,
                    "location": location,
                    "occurred_at": occurred_at,
                })
    stop_events.sort(key=lambda item: item["occurred_at"])

    return render(request, "dashboard/driver_logs.html", {
        "selected_day": selected_day.isoformat(),
        "daily_drivers": daily_drivers,
        "stop_events": stop_events,
    })

# DRIVERS
# ==========================================================

def _save_driver_login(form, driver):
    username = form.cleaned_data.get("login_username", "").strip()
    password = form.cleaned_data.get("login_password", "")
    if not username and not password:
        if driver.user_id:
            return True
        form.add_error("login_username", "A username and password are required for driver app access.")
        return False

    User = get_user_model()
    users = User.objects.filter(username=username)
    if driver.user_id:
        users = users.exclude(pk=driver.user_id)
    if users.exists():
        form.add_error("login_username", "That username is already in use.")
        return False

    if driver.user_id:
        user = driver.user
        user.username = username
        if password:
            user.set_password(password)
        user.save()
    else:
        if not username or not password:
            form.add_error("login_password", "A username and password are required for driver app access.")
            return False
        user = User.objects.create_user(username=username, password=password)
    driver.user = user
    return True

def drivers(request):
    return render(
        request,
        "dashboard/drivers.html",
        {"drivers": _scope_queryset(request, Driver)},
    )


def add_driver(request):
    form = DriverForm(request.POST or None, account=request.account, client_company_ids=_form_company_ids(request))
    form.fields["login_username"].required = True
    form.fields["login_password"].required = True

    if request.method == "POST" and form.is_valid():
        driver = form.save(commit=False)

        if not _save_driver_login(form, driver):
            return render(request, "dashboard/add_driver.html", {"form": form})

        location_result = geocode_address(driver.location)
        if location_result:
            driver.latitude = location_result["latitude"]
            driver.longitude = location_result["longitude"]

        driver.account = request.account
        driver.save()
        return redirect("drivers")

    return render(
        request,
        "dashboard/add_driver.html",
        {"form": form},
    )


def edit_driver(request, driver_id):
    driver = get_object_or_404(_scope_queryset(request, Driver), id=driver_id)

    form = DriverForm(
        request.POST or None,
        instance=driver,
        account=request.account,
        client_company_ids=_form_company_ids(request),
    )

    if request.method == "POST" and form.is_valid():
        driver = form.save(commit=False)

        if not _save_driver_login(form, driver):
            return render(request, "dashboard/edit_driver.html", {"driver": driver, "form": form})

        location_result = geocode_address(driver.location)
        if location_result:
            driver.latitude = location_result["latitude"]
            driver.longitude = location_result["longitude"]

        driver.save()
        return redirect("drivers")

    return render(
        request,
        "dashboard/edit_driver.html",
        {
            "driver": driver,
            "form": form,
        },
    )


def delete_driver(request, driver_id):
    driver = get_object_or_404(_scope_queryset(request, Driver), id=driver_id)

    if request.method == "POST":
        driver.delete()
        return redirect("drivers")

    return render(
        request,
        "dashboard/delete_driver.html",
        {"driver": driver},
    )


# ==========================================================
# CUSTOMERS
# ==========================================================

def customers(request):
    if request.method == "POST":
        form = CustomerForm(request.POST, account=request.account, client_company_ids=_form_company_ids(request))
        if form.is_valid():
            customer = form.save(commit=False)
            customer.account = request.account
            customer.save()
            return redirect("customers")
    else:
        form = CustomerForm(account=request.account, client_company_ids=_form_company_ids(request))

    return render(
        request,
        "dashboard/customers.html",
        {
            "customers": _scope_queryset(request, Customer),
            "form": form,
        },
    )


def edit_customer(request, customer_id):
    customer = get_object_or_404(_scope_queryset(request, Customer), id=customer_id)
    form = CustomerForm(request.POST or None, instance=customer, account=request.account, client_company_ids=_form_company_ids(request))

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("customers")

    return render(
        request,
        "dashboard/edit_customer.html",
        {"customer": customer, "form": form},
    )


def delete_customer(request, customer_id):
    customer = get_object_or_404(_scope_queryset(request, Customer), id=customer_id)

    if request.method == "POST":
        customer.delete()
        return redirect("customers")

    return render(
        request,
        "dashboard/delete_customer.html",
        {"customer": customer},
    )


# ==========================================================
# TRUCKS
# ==========================================================

def trucks(request):
    return render(
        request,
        "dashboard/trucks.html",
        {"trucks": _scope_queryset(request, Truck)},
    )


def add_truck(request):
    form = TruckForm(request.POST or None, account=request.account, client_company_ids=_form_company_ids(request))

    if request.method == "POST" and form.is_valid():
        truck = form.save(commit=False)
        truck.account = request.account
        truck.save()
        return redirect("trucks")

    return render(
        request,
        "dashboard/add_truck.html",
        {"form": form},
    )


def edit_truck(request, truck_id):
    truck = get_object_or_404(_scope_queryset(request, Truck), id=truck_id)

    form = TruckForm(
        request.POST or None,
        instance=truck,
        account=request.account,
        client_company_ids=_form_company_ids(request),
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("trucks")

    return render(
        request,
        "dashboard/edit_truck.html",
        {
            "truck": truck,
            "form": form,
        },
    )


def delete_truck(request, truck_id):
    truck = get_object_or_404(_scope_queryset(request, Truck), id=truck_id)

    if request.method == "POST":
        truck.delete()
        return redirect("trucks")

    return render(
        request,
        "dashboard/delete_truck.html",
        {"truck": truck},
    )


# ==========================================================
# TRAILERS
# ==========================================================

def trailers(request):
    return render(
        request,
        "dashboard/trailers.html",
        {"trailers": _scope_queryset(request, Trailer)},
    )


def add_trailer(request):
    form = TrailerForm(request.POST or None, account=request.account, client_company_ids=_form_company_ids(request))

    if request.method == "POST" and form.is_valid():
        trailer = form.save(commit=False)
        trailer.account = request.account
        trailer.save()
        return redirect("trailers")

    return render(
        request,
        "dashboard/add_trailer.html",
        {"form": form},
    )


def edit_trailer(request, trailer_id):
    trailer = get_object_or_404(_scope_queryset(request, Trailer), id=trailer_id)

    form = TrailerForm(
        request.POST or None,
        instance=trailer,
        account=request.account,
        client_company_ids=_form_company_ids(request),
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("trailers")

    return render(
        request,
        "dashboard/edit_trailer.html",
        {
            "trailer": trailer,
            "form": form,
        },
    )


def delete_trailer(request, trailer_id):
    trailer = get_object_or_404(_scope_queryset(request, Trailer), id=trailer_id)

    if request.method == "POST":
        trailer.delete()
        return redirect("trailers")

    return render(
        request,
        "dashboard/delete_trailer.html",
        {"trailer": trailer},
    )


# ==========================================================
# LOADS
# ==========================================================

def loads(request):
    if request.method == "POST":
        form = LoadForm(request.POST, account=request.account, client_company_ids=_form_company_ids(request))

        if form.is_valid():
            load = form.save(commit=False)
            load.account = request.account
            load.company = load.customer.company

            pickup_result = geocode_address(load.pickup)
            delivery_result = geocode_address(load.delivery)

            if pickup_result:
                load.pickup_latitude = pickup_result["latitude"]
                load.pickup_longitude = pickup_result["longitude"]

            if delivery_result:
                load.delivery_latitude = delivery_result["latitude"]
                load.delivery_longitude = delivery_result["longitude"]

            load.save()
            return redirect("loads")
    else:
        form = LoadForm(account=request.account, client_company_ids=_form_company_ids(request))

    return render(
        request,
        "dashboard/loads.html",
        {
            "loads": _scope_queryset(request, Load),
            "form": form,
        },
    )
def load_detail(request, load_id):
    load = get_object_or_404(_scope_queryset(request, Load), id=load_id)

    return render(
        request,
        "dashboard/load_detail.html",
        {"load": load},
    )


def complete_load(request, load_id):
    if request.method != "POST":
        return redirect("load_detail", load_id=load_id)

    load = get_object_or_404(_scope_queryset(request, Load), id=load_id)
    if load.status != "Assigned":
        messages.error(request, "Only an assigned load can be marked delivered.")
        return redirect("load_detail", load_id=load.id)

    with transaction.atomic():
        load.status = "Delivered"
        load.save(update_fields=["status"])

        if load.driver_id:
            Driver.objects.filter(
                id=load.driver_id,
                account=request.account,
                company_id=load.company_id,
            ).update(
                available=True,
                status="Available",
            )
        if load.truck_id:
            Truck.objects.filter(
                id=load.truck_id,
                account=request.account,
                company_id=load.company_id,
            ).update(active=True)
        if load.trailer_id:
            Trailer.objects.filter(
                id=load.trailer_id,
                account=request.account,
                company_id=load.company_id,
            ).update(available=True)

    messages.success(
        request,
        "Load marked delivered. Its driver, truck, and trailer are available again.",
    )
    return redirect("load_detail", load_id=load.id)


def edit_load(request, load_id):
    load = get_object_or_404(_scope_queryset(request, Load), id=load_id)

    if request.method == "POST":
        form = LoadForm(request.POST, instance=load, account=request.account, client_company_ids=_form_company_ids(request))

        if form.is_valid():
            load = form.save(commit=False)
            load.company = load.customer.company

            pickup_result = geocode_address(load.pickup)
            delivery_result = geocode_address(load.delivery)

            if pickup_result:
                load.pickup_latitude = pickup_result["latitude"]
                load.pickup_longitude = pickup_result["longitude"]

            if delivery_result:
                load.delivery_latitude = delivery_result["latitude"]
                load.delivery_longitude = delivery_result["longitude"]

            load.save()

            save_load_profit(load)

            return redirect("load_detail", load_id=load.id)

    else:
        form = LoadForm(instance=load, account=request.account, client_company_ids=_form_company_ids(request))

    return render(
        request,
        "dashboard/edit_load.html",
        {
            "form": form,
            "load": load,
        },
    )


def delete_load(request, load_id):
    load = get_object_or_404(_scope_queryset(request, Load), id=load_id)

    if request.method == "POST":
        load.delete()
        return redirect("loads")

    return render(
        request,
        "dashboard/delete_load.html",
        {"load": load},
    )


# ==========================================================
# AI DISPATCH
# ==========================================================

def ai_dispatch(request):
    available_drivers = (
        _scope_queryset(request, Driver).filter(
            available=True,
            status="Available",
        )
        .order_by("-ai_score", "-hours_remaining")
    )

    available_trucks = _scope_queryset(request, Truck).filter(
        active=True
    ).order_by("-capacity")

    available_trailers = _scope_queryset(request, Trailer).filter(
        available=True
    ).order_by("-capacity")

    available_loads = _scope_queryset(request, Load).filter(
        status="Available"
    ).order_by(
        "-priority",
        "pickup_datetime",
    )

    best_load = available_loads.first()

    best_driver = (
        select_best_driver(best_load)
        if best_load
        else None
    )

    best_truck = (
        select_best_truck(best_load)
        if best_load
        else None
    )

    best_trailer = (
        select_best_trailer(best_load)
        if best_load
        else None
    )

    route = (
        calculate_route(best_load)
        if best_load
        else None
    )

    ai_score = 0
    ai_reasons = []

    if best_driver:
        ai_score += 25
        ai_reasons.append("✔ Best Driver Available")

        if getattr(best_driver, "hours_remaining", 0) > 0:
            ai_score += 15
            ai_reasons.append("✔ Driver Has Hours Available")

    if best_truck:
        ai_score += 20
        ai_reasons.append("✔ Truck Available")

    if best_trailer:
        ai_score += 20
        ai_reasons.append("✔ Trailer Available")

    if best_load:
        ai_score += 20
        ai_reasons.append("✔ Load Ready")

        if getattr(best_load, "priority", "") == "High":
            ai_score += 10
            ai_reasons.append("✔ High Priority Load")

    ai_score = min(ai_score, 100)
    driver_to_pickup_miles = None
    driver_pickup_eta = None
    best_fuel_stop = None

    context = {
        "drivers": available_drivers,
        "trucks": available_trucks,
        "trailers": available_trailers,
        "loads": available_loads,
        "best_driver": best_driver,
        "best_truck": best_truck,
        "best_trailer": best_trailer,
        "best_load": best_load,
        "route": route,
        "ai_score": ai_score,
        "ai_reasons": ai_reasons,
        "driver_to_pickup_miles": driver_to_pickup_miles,
        "driver_pickup_eta": driver_pickup_eta,
        "best_fuel_stop": best_fuel_stop,
    }

    return render(
        request,
        "dashboard/ai_dispatch.html",
        context,
    )


# ==========================================================
# DISPATCH BOARD
# ==========================================================

def dispatch_board(request):

    available_drivers = list(_scope_queryset(request, Driver).filter(
        available=True,
        status="Available",
    ))

    for driver in available_drivers:

        score = 0

        if driver.available:
            score += 40

        if getattr(driver, "hours_remaining", 0) >= 8:
            score += 30

        elif getattr(driver, "hours_remaining", 0) >= 4:
            score += 20

        else:
            score += 10

        if getattr(driver, "truck", None):
            score += 20

        driver.ai_score = score


    # ==========================================================
    # AI PLANS
    # ==========================================================

    all_loads = _scope_queryset(request, Load).filter(
        status="Available"
    )

    plans = build_plans(
        all_loads
    )

    best_plan = (
        plans[0]
        if plans
        else None
    )

    # ==========================================================
    # DEFAULT VALUES
    # ==========================================================

    driver_to_pickup_miles = None
    driver_pickup_eta = None
    best_fuel_stop = None

    # ==========================================================
    # AI FUEL SOLUTION
    # ==========================================================

    if best_plan:

        fuel_mpg = (
            best_plan["profit"].get(
                "mpg",
                7.0,
            )
        )

        trip_miles = (
            best_plan["route"].get(
                "miles",
                0,
            )
        )

        # ------------------------------------------------------
        # TEST DIESEL STATIONS
        # ------------------------------------------------------

        test_stations = [
            {
                "brand": "Pilot",
                "name": "Pilot Travel Center",
                "address": "Route Stop A",
                "price_per_gallon": 3.20,
                "detour_miles": 0.6,
            },
            {
                "brand": "Love's",
                "name": "Love's Travel Stop",
                "address": "Route Stop B",
                "price_per_gallon": 3.25,
                "detour_miles": 0.5,
            },
            {
                "brand": "TA",
                "name": "TA Travel Center",
                "address": "Route Stop C",
                "price_per_gallon": 3.27,
                "detour_miles": 0.7,
            },
            {
                "brand": "QuikTrip",
                "name": "QuikTrip",
                "address": "Route Stop D",
                "price_per_gallon": 3.18,
                "detour_miles": 0.4,
            },
        ]

        best_fuel_stop = find_best_fuel_stop(
            test_stations,
            trip_miles,
            fuel_mpg,
        )

        # ======================================================
        # DRIVER → PICKUP
        # ======================================================

        driver = best_plan.get("driver")
        load = best_plan.get("load")

        if driver and load:
            driver_to_pickup_miles = (
                best_plan.get("driver_road_miles")
                or best_plan.get("driver_distance")
            )

            if driver_to_pickup_miles is None:
                driver_to_pickup_miles = calculate_driver_distance(
                    driver,
                    load,
                )

            if driver_to_pickup_miles is not None:
                driver_pickup_eta = round(
                    driver_to_pickup_miles / 60,
                    1,
                )

    # =========================================================
    # RECOMMENDATIONS
    # =========================================================

    recommended_driver = max(available_drivers, key=lambda driver: driver.ai_score, default=None)

    recommended_truck = (
        _scope_queryset(request, Truck)
        .filter(active=True)
        .first()
    )

    recommended_trailer = (
        _scope_queryset(request, Trailer)
        .filter(available=True)
        .first()
    )

    # ==========================================================
    # CONTEXT
    # ==========================================================

    context = {
        "loads": _scope_queryset(request, Load),
        "drivers": available_drivers,
        "trucks": _scope_queryset(request, Truck),
        "trailers": _scope_queryset(request, Trailer),
        "plans": plans,
        "best_plan": best_plan,
        "best_fuel_stop": best_fuel_stop,
        "driver_to_pickup_miles": driver_to_pickup_miles,
        "driver_pickup_eta": driver_pickup_eta,
        "recommended_driver": recommended_driver,
        "recommended_truck": recommended_truck,
        "recommended_trailer": recommended_trailer,
    }
    return render(
        request,
        "dashboard/dispatch_board.html",
        context,
    )

# ==========================================================
# ASSIGN LOAD
# ==========================================================

def assign_load(request, load_id):

    if request.method != "POST":
        return redirect("dispatch_board")

    load = get_object_or_404(_scope_queryset(request, Load, writable=True), id=load_id)

    driver = select_best_driver(load)
    truck = select_best_truck(load)
    trailer = select_best_trailer(load)

    if not driver:
        messages.error(
            request,
            "❌ Dispatch failed: No available driver."
        )
        return redirect("dispatch_board")

    if not truck:
        messages.error(
            request,
            "❌ Dispatch failed: No available truck."
        )
        return redirect("dispatch_board")

    if not trailer:
        messages.error(
            request,
            "❌ Dispatch failed: No available trailer."
        )
        return redirect("dispatch_board")

    load.driver = driver
    load.truck = truck
    load.trailer = trailer
    load.status = "Assigned"

    driver.available = False
    driver.status = "Driving"

    truck.active = False
    trailer.available = False

    load.save()
    driver.save()
    truck.save()
    trailer.save()

    messages.success(
        request,
        f"✅ Load {load.id} dispatched successfully! "
        f"Driver: {driver.name} | "
        f"Truck: {truck.unit_number} | "
        f"Trailer: {trailer.trailer_number}"
    )

    return redirect("dispatch_board")

# ==========================================================
# PLAN ALL LOADS
# ==========================================================

def plan_all_loads(request):
    if request.method != "POST":
        return redirect("dispatch_board")

    loads_to_plan = _scope_queryset(request, Load, writable=True).filter(status="Available")

    for load in loads_to_plan:
        driver = select_best_driver(load)
        truck = select_best_truck(load)
        trailer = select_best_trailer(load)

        if driver and truck and trailer:
            load.driver = driver
            load.truck = truck
            load.trailer = trailer
            load.status = "Assigned"

            driver.available = False
            driver.status = "Driving"

            truck.active = False
            trailer.available = False

            load.save()
            driver.save()
            truck.save()
            trailer.save()

    return redirect("dispatch_board")


# ==========================================================
# DISPATCH RECOMMENDED LOAD
# ==========================================================

def dispatch_recommended_load(request):
    if request.method != "POST":
        return redirect("dispatch_board")

    plans = build_plans(_scope_queryset(request, Load, writable=True))

    if not plans:
        return redirect("dispatch_board")

    best_plan = plans[0]

    load = best_plan["load"]
    driver = best_plan["driver"]
    truck = best_plan["truck"]
    trailer = best_plan["trailer"]

    if not driver or not truck or not trailer:
        return redirect("dispatch_board")

    load.driver = driver
    load.truck = truck
    load.trailer = trailer
    load.status = "Assigned"

    driver.available = False
    driver.status = "Driving"

    truck.active = False
    trailer.available = False

    load.save()
    driver.save()
    truck.save()
    trailer.save()

    return redirect("dispatch_board")


# ==========================================================
# COMPANIES
# ==========================================================

def companies(request):
    if request.method == "POST":
        form = CompanyForm(request.POST)
        if form.is_valid():
            company = form.save(commit=False)
            company.account = request.account
            company.save()
            return redirect("companies")
    else:
        form = CompanyForm()

    return render(
        request,
        "dashboard/companies.html",
        {
            "companies": Company.objects.filter(account=request.account),
            "form": form,
        },
    )


def edit_company(request, company_id):
    company = get_object_or_404(Company, id=company_id, account=request.account)
    form = CompanyForm(request.POST or None, instance=company)

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("companies")

    return render(
        request,
        "dashboard/edit_company.html",
        {"company": company, "form": form},
    )


# ==========================================================
# FLEET MAP
# ==========================================================

def fleet_map(request):
    trucks = _scope_queryset(request, Truck).filter(active=True)

    return render(
        request,
        "dashboard/fleet_map.html",
        {"trucks": trucks},
    )


# ==========================================================
# TRUCK DETAIL
# ==========================================================

def truck_detail(request, truck_id):
    truck = get_object_or_404(_scope_queryset(request, Truck), id=truck_id)

    return render(
        request,
        "dashboard/truck_detail.html",
        {"truck": truck},
    )
