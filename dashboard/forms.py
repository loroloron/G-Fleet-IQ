from django import forms
from django.utils.translation import gettext_lazy as _

from fleet.models import (
    Company,
    Customer,
    Load,
    Driver,
    Truck,
    Trailer,
)


# ==========================================================
# CUSTOMER FORM
# ==========================================================

class CustomerForm(forms.ModelForm):

    class Meta:
        model = Customer
        fields = [
            "name",
            "location",
            "company",
        ]
        labels = {"name": _("Name"), "location": _("Location"), "company": _("Client company")}

    def __init__(self, *args, account=None, client_company_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if account is not None:
            companies = Company.objects.filter(account=account)
            if client_company_ids is not None:
                companies = companies.filter(id__in=client_company_ids)
                self.fields["company"].required = True
            self.fields["company"].queryset = companies


# ==========================================================
# LOAD FORM
# ==========================================================

class LoadForm(forms.ModelForm):

    pickup_datetime = forms.DateTimeField(
        input_formats=[
            "%m/%d/%Y %I:%M %p"
        ],
        widget=forms.TextInput(
            attrs={
                "placeholder": "MM/DD/YYYY HH:MM AM/PM",
            }
        ),
    )

    delivery_datetime = forms.DateTimeField(
        input_formats=[
            "%m/%d/%Y %I:%M %p"
        ],
        widget=forms.TextInput(
            attrs={
                "placeholder": "MM/DD/YYYY HH:MM AM/PM",
            }
        ),
    )

    class Meta:
        model = Load

        fields = [
            "customer",
            "pickup",
            "delivery",
            "pickup_datetime",
            "delivery_datetime",
            "weight",
            "miles",
            "rate",
            "equipment_type",
            "priority",
            "distance",
            "fuel_cost",
            "driver_pay",
            "tolls",
            "maintenance_cost",
            "insurance_cost",
        ]
        labels = {
            "customer": _("Customer"),
            "pickup": _("Pickup location"),
            "delivery": _("Delivery location"),
            "pickup_datetime": _("Pickup date and time"),
            "delivery_datetime": _("Delivery date and time"),
            "weight": _("Weight"),
            "miles": _("Miles"),
            "rate": _("Rate"),
            "equipment_type": _("Equipment type"),
            "priority": _("Priority"),
            "distance": _("Distance"),
            "fuel_cost": _("Fuel cost"),
            "driver_pay": _("Driver pay"),
            "tolls": _("Tolls"),
            "maintenance_cost": _("Maintenance cost"),
            "insurance_cost": _("Insurance cost"),
        }

    def __init__(self, *args, account=None, client_company_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if account is not None:
            customers = Customer.objects.filter(account=account)
            if client_company_ids is not None:
                customers = customers.filter(company_id__in=client_company_ids)
            self.fields["customer"].queryset = customers
        self.fields["priority"].choices = [
            (value, _(label)) for value, label in self.fields["priority"].choices
        ]


# ==========================================================
# DRIVER FORM
# ==========================================================

class DriverForm(forms.ModelForm):
    login_username = forms.CharField(
        required=False,
        max_length=150,
        label=_("Driver app username"),
        help_text=_("Give the driver this username to sign in to the mobile app."),
    )
    login_password = forms.CharField(
        required=False,
        min_length=8,
        label=_("Driver app password"),
        widget=forms.PasswordInput,
        help_text=_("Enter a new password here to create or reset mobile app access."),
    )

    class Meta:
        model = Driver

        exclude = ("account", "user")
        labels = {
            "name": _("Name"), "location": _("Location"),
            "latitude": _("Latitude"), "longitude": _("Longitude"),
            "available": _("Available"), "status": _("Status"),
            "truck_capacity": _("Truck capacity"),
            "hours_remaining": _("Hours remaining"), "phone": _("Phone"),
            "ai_score": _("AI score"), "miles_today": _("Miles today"),
            "loads_completed": _("Loads completed"),
            "fuel_efficiency": _("Fuel efficiency"),
            "shift_start": _("Shift start"), "shift_end": _("Shift end"),
            "home_terminal": _("Home terminal"), "truck": _("Truck"),
            "company": _("Company"),
        }

    def __init__(self, *args, account=None, client_company_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.user_id:
            self.fields["login_username"].initial = self.instance.user.get_username()
        if account is not None:
            companies = Company.objects.filter(account=account)
            trucks = Truck.objects.filter(account=account)
            if client_company_ids is not None:
                companies = companies.filter(id__in=client_company_ids)
                trucks = trucks.filter(company_id__in=client_company_ids)
                self.fields["company"].required = True
            self.fields["company"].queryset = companies
            self.fields["truck"].queryset = trucks
        self.fields["status"].choices = [
            (value, _(label)) for value, label in self.fields["status"].choices
        ]

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get("login_username", "").strip()
        password = cleaned.get("login_password", "")
        if bool(username) != bool(password) and not (self.instance.pk and self.instance.user_id and username):
            self.add_error("login_password", _("Enter both a username and password to set up driver app access."))
        return cleaned


# ==========================================================
# TRUCK FORM
# ==========================================================

class TruckForm(forms.ModelForm):

    class Meta:
        model = Truck

        exclude = ("account",)
        labels = {
            "unit_number": _("Unit number"), "capacity": _("Capacity"),
            "active": _("Active"), "latitude": _("Latitude"),
            "longitude": _("Longitude"), "company": _("Company"),
        }

    def __init__(self, *args, account=None, client_company_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if account is not None:
            companies = Company.objects.filter(account=account)
            if client_company_ids is not None:
                companies = companies.filter(id__in=client_company_ids)
                self.fields["company"].required = True
            self.fields["company"].queryset = companies


# ==========================================================
# TRAILER FORM
# ==========================================================

class TrailerForm(forms.ModelForm):

    class Meta:
        model = Trailer

        exclude = ("account",)
        labels = {
            "trailer_number": _("Trailer number"), "status": _("Status"),
            "location": _("Location"), "capacity": _("Capacity"),
            "available": _("Available"), "utilization": _("Utilization"),
            "last_inspection": _("Last inspection"), "company": _("Company"),
        }

    def __init__(self, *args, account=None, client_company_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if account is not None:
            companies = Company.objects.filter(account=account)
            if client_company_ids is not None:
                companies = companies.filter(id__in=client_company_ids)
                self.fields["company"].required = True
            self.fields["company"].queryset = companies
        self.fields["status"].choices = [
            (value, _(label)) for value, label in self.fields["status"].choices
        ]


# ==========================================================
# COMPANY FORM
# ==========================================================

class CompanyForm(forms.ModelForm):

    class Meta:
        model = Company

        exclude = ("account",)
        labels = {
            "name": _("Name"),
            "dot_number": _("DOT number"),
            "mc_number": _("MC number"),
            "email": _("Email"),
            "phone": _("Phone"),
            "active": _("Active"),
        }
