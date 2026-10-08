import uuid
from django.db import models
from decimal import Decimal
from django.conf import settings
from django.utils.translation import gettext_lazy as _

class FleetAccount(models.Model):
    name = models.CharField(max_length=200, default="G Fleet IQ Account")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class SamsaraConnection(models.Model):
    """OAuth credentials for one customer's Samsara organization."""

    company = models.OneToOneField(
        "Company",
        on_delete=models.CASCADE,
        related_name="samsara_connection",
    )
    organization_id = models.CharField(max_length=100, blank=True)
    organization_name = models.CharField(max_length=200, blank=True)
    access_token_encrypted = models.TextField()
    refresh_token_encrypted = models.TextField()
    access_token_expires_at = models.DateTimeField()
    scopes = models.CharField(max_length=500, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="samsara_connections_created",
    )

    def __str__(self):
        return self.organization_name or f"Samsara connection for {self.company}"


class AccountMembership(models.Model):
    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_OWNER, _("Account owner")),
        (ROLE_ADMIN, _("Administrator")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fleet_account_memberships",
    )
    account = models.ForeignKey(
        FleetAccount,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                name="unique_user_fleet_account_membership",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.account} ({self.get_role_display()})"


class Company(models.Model):
    account = models.ForeignKey("FleetAccount", on_delete=models.CASCADE, related_name="clients")
    name = models.CharField(max_length=200)
    dot_number = models.CharField(max_length=50, blank=True)
    mc_number = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    active = models.BooleanField(default=True)
    def __str__(self):
        return self.name


class CompanyInvoice(models.Model):
    STATUS_ISSUED = "issued"
    STATUS_PAID = "paid"
    STATUS_VOID = "void"
    STATUS_CHOICES = [
        (STATUS_ISSUED, _("Issued")),
        (STATUS_PAID, _("Paid")),
        (STATUS_VOID, _("Void")),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invoices")
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField()
    truck_count = models.PositiveIntegerField(default=0)
    trailer_count = models.PositiveIntegerField(default=0)
    truck_rate = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("30.00"))
    trailer_rate = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("15.00"))
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_ISSUED)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="company_invoices_created",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="company_invoices_paid",
    )

    class Meta:
        ordering = ["-period_start", "company__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "period_start", "period_end"],
                name="unique_company_invoice_period",
            )
        ]

    @property
    def total(self):
        return self.truck_amount + self.trailer_amount

    @property
    def amount_due(self):
        return self.total if self.status == self.STATUS_ISSUED else Decimal("0.00")

    @property
    def truck_amount(self):
        return self.truck_count * self.truck_rate

    @property
    def trailer_amount(self):
        return self.trailer_count * self.trailer_rate

    @property
    def invoice_number(self):
        return f"GFI-{self.period_start:%Y%m}-{self.pk:06d}"

    def __str__(self):
        return f"{self.invoice_number} — {self.company.name}"


class InvoicePayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(CompanyInvoice, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=10, choices=[("stripe", "Stripe"), ("paypal", "PayPal")])
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, default="pending", choices=[
        ("pending", "Pending"), ("succeeded", "Succeeded"), ("cancelled", "Cancelled"), ("review", "Needs review")])
    external_id = models.CharField(max_length=255, blank=True)
    checkout_url = models.URLField(max_length=2048, blank=True)
    reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invoice"], condition=models.Q(status="pending"),
                                    name="one_pending_payment_per_invoice"),
            models.UniqueConstraint(fields=["provider", "external_id"], condition=~models.Q(external_id=""),
                                    name="unique_provider_checkout"),
        ]


class CompanyMembership(models.Model):
    ROLE_CLIENT_ADMIN = "client_admin"
    ROLE_DISPATCHER = "dispatcher"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_CLIENT_ADMIN, _("Client administrator")),
        (ROLE_DISPATCHER, _("Dispatcher")),
        (ROLE_VIEWER, _("Read only")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="client_memberships",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company"],
                name="unique_user_client_membership",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.company} ({self.get_role_display()})"


class Truck(models.Model):
    account = models.ForeignKey(FleetAccount, on_delete=models.CASCADE, related_name="trucks")
    unit_number = models.CharField(max_length=50)
    capacity = models.IntegerField(default=40000)
    active = models.BooleanField(default=True)
    latitude = models.FloatField(default=39.7684)
    longitude = models.FloatField(default=-86.1581)
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="trucks",null=True,blank=True)
    def __str__(self):
        return self.unit_number

class Trailer(models.Model):
    account = models.ForeignKey(FleetAccount, on_delete=models.CASCADE, related_name="trailers")
    STATUS_CHOICES=[("Empty","Empty"),("Loaded","Loaded"),("Maintenance","Maintenance"),("Out of Service","Out of Service")]
    trailer_number=models.CharField(max_length=50,unique=True)
    status=models.CharField(max_length=20,choices=STATUS_CHOICES,default="Empty")
    location=models.CharField(max_length=200,blank=True,default="")
    capacity=models.IntegerField(default=53000)
    available=models.BooleanField(default=True)
    utilization=models.FloatField(default=0)
    last_inspection=models.DateField(null=True,blank=True)
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name="trailers",null=True,blank=True)
    def __str__(self):
        return self.trailer_number

class Driver(models.Model):
    account = models.ForeignKey(FleetAccount, on_delete=models.CASCADE, related_name="drivers")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="driver_profile",
    )
    STATUS_CHOICES=[("Available","Available"),("Driving","Driving"),("Off Duty","Off Duty"),("On Break","On Break")]
    name=models.CharField(max_length=100)
    location=models.CharField(max_length=200,blank=True,default="")
    latitude = models.FloatField(
    default=39.7684
)

    longitude = models.FloatField(
    default=-86.1581
)
    available=models.BooleanField(default=True)
    status=models.CharField(max_length=20,choices=STATUS_CHOICES,default="Available")
    truck_capacity=models.IntegerField(default=53000)
    hours_remaining=models.IntegerField(default=11)
    phone=models.CharField(max_length=20,blank=True,default="")
    ai_score=models.IntegerField(default=0)
    miles_today=models.IntegerField(default=0)
    loads_completed=models.IntegerField(default=0)
    fuel_efficiency=models.FloatField(default=7.0)
    shift_start=models.TimeField(null=True,blank=True)
    shift_end=models.TimeField(null=True,blank=True)
    home_terminal=models.CharField(max_length=100,blank=True,default="")
    truck=models.ForeignKey(Truck,on_delete=models.SET_NULL,null=True,blank=True)
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name="drivers",null=True,blank=True)
    def __str__(self):
        return self.name

class Customer(models.Model):
    account = models.ForeignKey(FleetAccount, on_delete=models.CASCADE, related_name="customers")
    name=models.CharField(max_length=100)
    location=models.CharField(max_length=200)
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name="customers",null=True,blank=True)
    def __str__(self):
        return self.name

class Load(models.Model):
    account = models.ForeignKey(FleetAccount, on_delete=models.CASCADE, related_name="loads")
    PRIORITY_CHOICES=[("Low","Low"),("Normal","Normal"),("High","High"),("Critical","Critical")]
    customer=models.ForeignKey(Customer,on_delete=models.CASCADE,related_name="loads")
    pickup=models.CharField(max_length=200)
    delivery=models.CharField(max_length=200)
    pickup_latitude = models.FloatField(
    null=True,
    blank=True,
)

    pickup_longitude = models.FloatField(
    null=True,
    blank=True,
)
    delivery_latitude = models.FloatField(
    null=True,
    blank=True,
)

    delivery_longitude = models.FloatField(
    null=True,
    blank=True,
)
    pickup_datetime=models.DateTimeField(null=True,blank=True)
    delivery_datetime=models.DateTimeField(null=True,blank=True)
    equipment_type=models.CharField(max_length=50,default="Dry Van")
    priority=models.CharField(max_length=20,choices=PRIORITY_CHOICES,default="Normal")
    weight=models.IntegerField(default=0)
    miles=models.IntegerField(default=0)
    distance=models.IntegerField(default=0)
    rate=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    fuel_cost=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    driver_pay=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    tolls=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    maintenance_cost=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    insurance_cost=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    profit=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    profit_per_mile=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    status=models.CharField(max_length=50,default="Available")
    pickup_arrived_at=models.DateTimeField(null=True,blank=True)
    pickup_departed_at=models.DateTimeField(null=True,blank=True)
    delivery_arrived_at=models.DateTimeField(null=True,blank=True)
    delivery_departed_at=models.DateTimeField(null=True,blank=True)
    driver=models.ForeignKey(Driver,on_delete=models.SET_NULL,null=True,blank=True)
    truck=models.ForeignKey(Truck,on_delete=models.SET_NULL,null=True,blank=True)
    trailer=models.ForeignKey(Trailer,on_delete=models.SET_NULL,null=True,blank=True)
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name="loads",null=True,blank=True)
    def __str__(self):
        return f"{self.customer} | {self.pickup} → {self.delivery}"


class DriverDutyLog(models.Model):
    STATUS_OFF_DUTY = "off_duty"
    STATUS_ON_DUTY = "on_duty"
    STATUS_DRIVING = "driving"
    STATUS_CHOICES = [
        (STATUS_OFF_DUTY, "Off duty"),
        (STATUS_ON_DUTY, "On duty, not driving"),
        (STATUS_DRIVING, "Driving"),
    ]
    SOURCE_MANUAL = "manual"
    SOURCE_AUTOMATIC = "automatic"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_AUTOMATIC, "Automatic movement detection"),
    ]

    account = models.ForeignKey(FleetAccount, on_delete=models.CASCADE, related_name="driver_duty_logs")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="duty_logs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    movement_distance_miles = models.FloatField(default=0)
    last_latitude = models.FloatField(null=True, blank=True)
    last_longitude = models.FloatField(null=True, blank=True)
    last_location_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["started_at", "id"]
        indexes = [
            models.Index(fields=["account", "started_at"], name="duty_account_start_idx"),
            models.Index(fields=["driver", "started_at"], name="duty_driver_start_idx"),
        ]

    def __str__(self):
        return f"{self.driver.name} — {self.get_status_display()} — {self.started_at}"
