import math
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from fleet.models import (
    AccountMembership,
    Company,
    CompanyMembership,
    Customer,
    Driver,
    DriverDutyLog,
    Load,
    Trailer,
    Truck,
)
from .ai_engine import select_best_driver, select_best_trailer, select_best_truck


def _access_for(user):
    account_membership = (
        AccountMembership.objects.filter(user=user, active=True)
        .select_related("account")
        .first()
    )
    client_memberships = list(
        CompanyMembership.objects.filter(user=user, active=True)
        .select_related("company", "company__account")
    )
    account = account_membership.account if account_membership else None
    if account is None and client_memberships:
        account = client_memberships[0].company.account
    if account is None:
        return None

    account_admin = account_membership is not None
    visible_company_ids = {item.company_id for item in client_memberships}
    writable_company_ids = {
        item.company_id
        for item in client_memberships
        if item.role in {
            CompanyMembership.ROLE_CLIENT_ADMIN,
            CompanyMembership.ROLE_DISPATCHER,
        }
    }
    return {
        "account": account,
        "account_membership": account_membership,
        "client_memberships": client_memberships,
        "account_admin": account_admin,
        "can_dispatch": account_admin or bool(writable_company_ids),
        "visible_company_ids": visible_company_ids,
        "writable_company_ids": writable_company_ids,
    }


def _scoped(queryset, access, writable=False):
    if access["account_admin"]:
        return queryset.filter(account=access["account"])
    company_ids = (
        access["writable_company_ids"]
        if writable
        else access["visible_company_ids"]
    )
    return queryset.filter(
        account=access["account"],
        company_id__in=company_ids,
    )


def _account_role(access):
    if access["account_membership"]:
        return access["account_membership"].role
    return access["client_memberships"][0].role if access["client_memberships"] else ""


def _load_data(load):
    return {
        "id": load.pk,
        "customer": load.customer.name,
        "pickup": load.pickup,
        "delivery": load.delivery,
        "pickup_datetime": load.pickup_datetime.isoformat() if load.pickup_datetime else None,
        "delivery_datetime": load.delivery_datetime.isoformat() if load.delivery_datetime else None,
        "status": load.status,
        "priority": load.priority,
        "driver": load.driver.name if load.driver_id else None,
        "truck": load.truck.unit_number if load.truck_id else None,
        "trailer": load.trailer.trailer_number if load.trailer_id else None,
        "company": load.company.name if load.company_id else "",
    }


class MobileLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mobile_login"

    def post(self, request):
        serializer = AuthTokenSerializer(
            data=request.data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return Response(
                {"detail": "Username or password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.validated_data["user"]
        driver = Driver.objects.filter(user=user).select_related("account", "company", "truck").first()
        access = _access_for(user)
        if driver is None and access is None:
            return Response(
                {"detail": "This user is not assigned to a G Fleet IQ account or driver yet."},
                status=status.HTTP_403_FORBIDDEN,
            )
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "token": token.key,
            "user": {"username": user.get_username()},
            "user_type": "driver" if driver else "office",
            "driver_name": driver.name if driver else "",
            "account": {
                "name": access["account"].name if access else "",
                "role": _account_role(access) if access else "",
                "can_dispatch": access["can_dispatch"] if access else False,
            },
        })


class MobileLogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MobileDashboardView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        access = _access_for(request.user)
        if access is None:
            return Response(
                {"detail": "This user is not assigned to a G Fleet IQ account yet."},
                status=status.HTTP_403_FORBIDDEN,
            )

        loads = _scoped(
            Load.objects.select_related("customer", "driver", "truck", "trailer", "company"),
            access,
        )
        drivers = _scoped(Driver.objects.all(), access)
        trucks = _scoped(Truck.objects.all(), access)
        trailers = _scoped(Trailer.objects.all(), access)
        membership = access["account_membership"]
        return Response({
            "username": request.user.get_username(),
            "account_name": access["account"].name,
            "role": _account_role(access),
            "can_dispatch": access["can_dispatch"],
            "can_manage_account": bool(membership and membership.role == AccountMembership.ROLE_OWNER),
            "summary": {
                "loads": loads.count(),
                "active_loads": loads.exclude(status__in=["Delivered", "Cancelled"]).count(),
                "available_drivers": drivers.filter(available=True, status="Available").count(),
                "trucks": trucks.count(),
                "available_trucks": trucks.filter(active=True).count(),
                "trailers": trailers.count(),
                "available_trailers": trailers.filter(available=True).count(),
            },
            "recent_loads": [
                _load_data(load)
                for load in loads.order_by("-id")[:5]
            ],
        })


class MobileLoadsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        access = _access_for(request.user)
        if access is None:
            return Response(
                {"detail": "This user is not assigned to a G Fleet IQ account yet."},
                status=status.HTTP_403_FORBIDDEN,
            )

        loads = _scoped(
            Load.objects.select_related("customer", "driver", "truck", "trailer", "company"),
            access,
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            loads = loads.filter(status=status_filter)
        return Response({
            "can_dispatch": access["can_dispatch"],
            "loads": [_load_data(load) for load in loads.order_by("-id")[:100]],
        })


def _driver_load_data(load):
    data = _load_data(load)
    data.update({
        "pickup_arrived_at": load.pickup_arrived_at.isoformat() if load.pickup_arrived_at else None,
        "pickup_departed_at": load.pickup_departed_at.isoformat() if load.pickup_departed_at else None,
        "delivery_arrived_at": load.delivery_arrived_at.isoformat() if load.delivery_arrived_at else None,
        "delivery_departed_at": load.delivery_departed_at.isoformat() if load.delivery_departed_at else None,
    })
    return data


def _duty_day_bounds(day):
    current_timezone = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), current_timezone)
    end = start + timedelta(days=1)
    return start, end


def _driver_duty_day(driver, day):
    start, end = _duty_day_bounds(day)
    now = timezone.now()
    entries = []
    totals = {key: 0 for key in ("off_duty", "on_duty", "driving")}
    logs = DriverDutyLog.objects.filter(
        account=driver.account,
        driver=driver,
        started_at__lt=end,
    ).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start)).order_by("started_at", "id")

    for log in logs:
        clipped_start = max(log.started_at, start)
        clipped_end = min(log.ended_at or now, end, now)
        seconds = max(0, int((clipped_end - clipped_start).total_seconds()))
        totals[log.status] += seconds
        is_active = log.ended_at is None and day == timezone.localdate()
        entries.append({
            "status": log.status,
            "status_label": log.get_status_display(),
            "source": log.source,
            "source_label": log.get_source_display(),
            "started_at": clipped_start.isoformat(),
            "ended_at": None if is_active else clipped_end.isoformat(),
            "duration_seconds": seconds,
            "active": is_active,
        })

    active = next((entry for entry in reversed(entries) if entry["active"]), None)
    stop_events = []
    for load in Load.objects.filter(account=driver.account, driver=driver).filter(
        Q(pickup_arrived_at__gte=start, pickup_arrived_at__lt=end)
        | Q(pickup_departed_at__gte=start, pickup_departed_at__lt=end)
        | Q(delivery_arrived_at__gte=start, delivery_arrived_at__lt=end)
        | Q(delivery_departed_at__gte=start, delivery_departed_at__lt=end)
    ).select_related("customer"):
        for field, label, location in (
            ("pickup_arrived_at", "Arrived at pickup", load.pickup),
            ("pickup_departed_at", "Departed pickup", load.pickup),
            ("delivery_arrived_at", "Arrived at delivery", load.delivery),
            ("delivery_departed_at", "Departed delivery", load.delivery),
        ):
            occurred_at = getattr(load, field)
            if occurred_at and start <= occurred_at < end:
                stop_events.append({
                    "label": label,
                    "occurred_at": occurred_at.isoformat(),
                    "customer": load.customer.name,
                    "location": location,
                })
    stop_events.sort(key=lambda item: item["occurred_at"])
    return {
        "date": day.isoformat(),
        "current_status": active["status"] if active else None,
        "current_status_label": active["status_label"] if active else "Not started",
        "totals": {
            **totals,
            "worked": totals["on_duty"] + totals["driving"],
        },
        "entries": entries,
        "stop_events": stop_events,
    }


class MobileDriverDutyLogView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        driver = Driver.objects.filter(user=request.user).select_related("account").first()
        if driver is None:
            return Response({"detail": "This sign-in is not linked to a driver."}, status=403)
        requested_day = request.query_params.get("date")
        try:
            day = datetime.strptime(requested_day, "%Y-%m-%d").date() if requested_day else timezone.localdate()
        except ValueError:
            return Response({"detail": "Use a date in YYYY-MM-DD format."}, status=400)
        return Response({"driver": driver.name, **_driver_duty_day(driver, day)})

    def post(self, request):
        driver = Driver.objects.filter(user=request.user).select_related("account").first()
        if driver is None:
            return Response({"detail": "This sign-in is not linked to a driver."}, status=403)
        selected_status = request.data.get("status")
        if selected_status not in dict(DriverDutyLog.STATUS_CHOICES):
            return Response({"detail": "Choose off_duty, on_duty, or driving."}, status=400)

        with transaction.atomic():
            locked_driver = Driver.objects.select_for_update().select_related("account").get(pk=driver.pk)
            current = DriverDutyLog.objects.select_for_update().filter(
                account=locked_driver.account,
                driver=locked_driver,
                ended_at__isnull=True,
            ).order_by("-started_at", "-id").first()
            if current and current.status == selected_status:
                return Response({"detail": "That duty status is already active."}, status=409)
            now = timezone.now()
            if current:
                current.ended_at = now
                current.last_latitude = None
                current.last_longitude = None
                current.last_location_at = None
                current.movement_distance_miles = 0
                current.save(update_fields=[
                    "ended_at", "last_latitude", "last_longitude",
                    "last_location_at", "movement_distance_miles",
                ])
            DriverDutyLog.objects.create(
                account=locked_driver.account,
                driver=locked_driver,
                status=selected_status,
                started_at=now,
            )
        return Response(_driver_duty_day(locked_driver, timezone.localdate()))


class MobileDriverLocationView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        driver = Driver.objects.filter(user=request.user).select_related("account").first()
        if driver is None:
            return Response({"detail": "This sign-in is not linked to a driver."}, status=403)
        try:
            latitude = float(request.data.get("latitude"))
            longitude = float(request.data.get("longitude"))
            accuracy = float(request.data.get("accuracy"))
            speed_mph = max(0, float(request.data.get("speed_mph") or 0))
        except (TypeError, ValueError):
            return Response({"detail": "A valid tablet location is required."}, status=400)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return Response({"detail": "The tablet location is invalid."}, status=400)

        with transaction.atomic():
            locked_driver = Driver.objects.select_for_update().select_related("account").get(pk=driver.pk)
            current = DriverDutyLog.objects.select_for_update().filter(
                account=locked_driver.account,
                driver=locked_driver,
                ended_at__isnull=True,
            ).order_by("-started_at", "-id").first()
            now = timezone.now()
            switched_to_driving = False

            if current is None:
                if accuracy <= 60 and speed_mph >= 10:
                    DriverDutyLog.objects.create(
                        account=locked_driver.account,
                        driver=locked_driver,
                        status=DriverDutyLog.STATUS_DRIVING,
                        source=DriverDutyLog.SOURCE_AUTOMATIC,
                        started_at=now,
                    )
                    switched_to_driving = True
            elif current.status != DriverDutyLog.STATUS_DRIVING and accuracy <= 60:
                segment_miles = 0
                if current.last_latitude is not None and current.last_longitude is not None and current.last_location_at:
                    elapsed = (now - current.last_location_at).total_seconds()
                    segment_miles = _great_circle_miles(
                        current.last_latitude, current.last_longitude, latitude, longitude
                    )
                    average_mph = segment_miles * 3600 / elapsed if elapsed > 0 else 999
                    if elapsed <= 0 or elapsed > 300 or average_mph < 3 or average_mph > 100 or segment_miles > 5:
                        segment_miles = 0
                current.movement_distance_miles += segment_miles
                current.last_latitude = latitude
                current.last_longitude = longitude
                current.last_location_at = now
                if speed_mph >= 10 or current.movement_distance_miles > 2:
                    current.ended_at = now
                    current.last_latitude = None
                    current.last_longitude = None
                    current.last_location_at = None
                    current.movement_distance_miles = 0
                    current.save(update_fields=[
                        "ended_at", "movement_distance_miles", "last_latitude",
                        "last_longitude", "last_location_at",
                    ])
                    DriverDutyLog.objects.create(
                        account=locked_driver.account,
                        driver=locked_driver,
                        status=DriverDutyLog.STATUS_DRIVING,
                        source=DriverDutyLog.SOURCE_AUTOMATIC,
                        started_at=now,
                    )
                    switched_to_driving = True
                else:
                    current.save(update_fields=[
                        "movement_distance_miles", "last_latitude", "last_longitude", "last_location_at",
                    ])

        return Response({
            **_driver_duty_day(locked_driver, timezone.localdate()),
            "automatic_change": switched_to_driving,
        })


def _great_circle_miles(latitude_a, longitude_a, latitude_b, longitude_b):
    earth_radius_miles = 3958.7613
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    lat_delta = lat_b - lat_a
    lon_delta = math.radians(longitude_b - longitude_a)
    value = math.sin(lat_delta / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(lon_delta / 2) ** 2
    return earth_radius_miles * 2 * math.asin(min(1, math.sqrt(value)))


class MobileDriverLoadsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        driver = Driver.objects.filter(user=request.user).select_related("account", "company", "truck").first()
        if driver is None:
            return Response({"detail": "This sign-in is not linked to a driver."}, status=403)
        loads = Load.objects.filter(
            account=driver.account,
            driver=driver,
            status="Assigned",
        ).select_related("customer", "driver", "truck", "trailer", "company").order_by("pickup_datetime", "id")
        return Response({
            "driver": driver.name,
            "truck": driver.truck.unit_number if driver.truck_id else "",
            "loads": [_driver_load_data(load) for load in loads[:25]],
        })


class MobileDriverStopActionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, load_id, action):
        driver = Driver.objects.filter(user=request.user).first()
        if driver is None:
            return Response({"detail": "This sign-in is not linked to a driver."}, status=403)
        allowed_actions = {
            "pickup-arrived": ("pickup_arrived_at", None),
            "pickup-departed": ("pickup_departed_at", "pickup_arrived_at"),
            "delivery-arrived": ("delivery_arrived_at", "pickup_departed_at"),
            "delivery-departed": ("delivery_departed_at", "delivery_arrived_at"),
        }
        if action not in allowed_actions:
            return Response({"detail": "Unknown driver action."}, status=404)

        with transaction.atomic():
            load = get_object_or_404(
                            Load.objects.select_for_update(),
                pk=load_id,
                account=driver.account,
                driver=driver,
                status="Assigned",
            )
            field, prerequisite = allowed_actions[action]
            if prerequisite and not getattr(load, prerequisite):
                return Response({"detail": "Complete the previous stop update first."}, status=409)
            if getattr(load, field):
                return Response({"detail": "This stop update was already recorded."}, status=409)

            setattr(load, field, timezone.now())
            updated_fields = [field]
            if action == "delivery-departed":
                load.status = "Delivered"
                updated_fields.append("status")
                Driver.objects.filter(pk=driver.pk).update(available=True, status="Available")
                if load.truck_id:
                    Truck.objects.filter(pk=load.truck_id, account=driver.account).update(active=True)
                if load.trailer_id:
                    Trailer.objects.filter(pk=load.trailer_id, account=driver.account).update(available=True)
            load.save(update_fields=updated_fields)
            load.refresh_from_db()
            return Response({"load": _driver_load_data(load)})


class MobileWorkspaceView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        access = _access_for(request.user)
        if access is None:
            return Response(
                {"detail": "This user is not assigned to a G Fleet IQ account yet."},
                status=status.HTTP_403_FORBIDDEN,
            )

        customers = _scoped(Customer.objects.select_related("company"), access).order_by("name")
        drivers = _scoped(Driver.objects.select_related("company", "truck"), access).order_by("name")
        trucks = _scoped(Truck.objects.select_related("company"), access).order_by("unit_number")
        trailers = _scoped(Trailer.objects.select_related("company"), access).order_by("trailer_number")

        companies = Company.objects.filter(account=access["account"]).order_by("name")
        if not access["account_admin"]:
            companies = companies.filter(pk__in=access["visible_company_ids"])

        if access["account_admin"]:
            team_company_ids = set(companies.values_list("pk", flat=True))
        else:
            team_company_ids = {
                item.company_id
                for item in access["client_memberships"]
                if item.role == CompanyMembership.ROLE_CLIENT_ADMIN
            }
        client_teams = []
        for company in companies.filter(pk__in=team_company_ids):
            members = CompanyMembership.objects.filter(
                company=company, active=True
            ).select_related("user").order_by("user__username")
            client_teams.append({
                "company": company.name,
                "members": [
                    {"username": member.user.get_username(), "role": member.get_role_display()}
                    for member in members
                ],
            })

        membership = access["account_membership"]
        can_manage_account = bool(
            membership and membership.role == AccountMembership.ROLE_OWNER
        )
        account_team = []
        if can_manage_account:
            account_team = [
                {"username": member.user.get_username(), "role": member.get_role_display()}
                for member in AccountMembership.objects.filter(
                    account=access["account"], active=True
                ).select_related("user").order_by("user__username")
            ]

        return Response({
            "can_manage_companies": access["account_admin"],
            "can_manage_account": can_manage_account,
            "can_view_client_teams": bool(team_company_ids),
            "can_add_records": access["can_dispatch"],
            "companies": [
                {"id": company.pk, "name": company.name, "dot_number": company.dot_number, "mc_number": company.mc_number,
                 "phone": company.phone, "email": company.email, "active": company.active}
                for company in companies
            ],
            "customers": [
                {"name": customer.name, "location": customer.location,
                 "company": customer.company.name if customer.company_id else ""}
                for customer in customers
            ],
            "drivers": [
                {"name": driver.name, "status": driver.status, "location": driver.location,
                 "available": driver.available, "truck": driver.truck.unit_number if driver.truck_id else "",
                 "company": driver.company.name if driver.company_id else ""}
                for driver in drivers
            ],
            "trucks": [
                {"unit_number": truck.unit_number, "status": "Available" if truck.active else "Assigned",
                 "capacity": truck.capacity, "latitude": truck.latitude, "longitude": truck.longitude,
                 "company": truck.company.name if truck.company_id else ""}
                for truck in trucks
            ],
            "trailers": [
                {"trailer_number": trailer.trailer_number, "status": trailer.status,
                 "available": trailer.available, "location": trailer.location,
                 "company": trailer.company.name if trailer.company_id else ""}
                for trailer in trailers
            ],
            "account_team": account_team,
            "client_teams": client_teams,
        })


class MobileCreateRecordView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        access = _access_for(request.user)
        if access is None:
            return Response({"detail": "This user is not assigned to a G Fleet IQ account yet."}, status=403)

        data = request.data
        kind = str(data.get("type", "")).strip().lower()
        account = access["account"]
        company_ids = access["writable_company_ids"]
        company_name = str(data.get("company", "")).strip()

        if kind == "companies":
            if not access["account_admin"]:
                return Response({"detail": "Only account administrators can add client companies."}, status=403)
            name = str(data.get("name", "")).strip()
            if not name:
                return Response({"detail": "Enter a company name."}, status=400)
            company = Company.objects.create(
                account=account,
                name=name,
                dot_number=str(data.get("dot_number", "")).strip(),
                mc_number=str(data.get("mc_number", "")).strip(),
                phone=str(data.get("phone", "")).strip(),
                email=str(data.get("email", "")).strip(),
            )
            return Response({"id": company.pk, "name": company.name}, status=201)

        if kind not in {"customers", "drivers", "trucks", "trailers", "loads"}:
            return Response({"detail": "Unknown category."}, status=400)
        if not access["can_dispatch"]:
            return Response({"detail": "Your access is read-only."}, status=403)

        company = None
        if company_name:
            companies = Company.objects.filter(account=account, name__iexact=company_name)
            if not access["account_admin"]:
                companies = companies.filter(pk__in=company_ids)
            company = companies.first()
            if company is None:
                return Response({"detail": "That company was not found in your account."}, status=400)
        elif not access["account_admin"] and len(company_ids) == 1:
            company = Company.objects.filter(pk=next(iter(company_ids)), account=account).first()

        if kind == "customers":
            name = str(data.get("name", "")).strip()
            location = str(data.get("location", "")).strip()
            if not name or not location:
                return Response({"detail": "Enter the customer name and location."}, status=400)
            if not access["account_admin"] and company is None:
                return Response({"detail": "Enter the client company name for this customer."}, status=400)
            record = Customer.objects.create(account=account, name=name, location=location, company=company)
            return Response({"id": record.pk, "name": record.name}, status=201)

        if kind == "drivers":
            name = str(data.get("name", "")).strip()
            username = str(data.get("login_username", "")).strip()
            password = str(data.get("login_password", ""))
            if not name:
                return Response({"detail": "Enter the driver name."}, status=400)
            if not username or len(password) < 8:
                return Response({"detail": "Enter a driver app username and a password of at least 8 characters."}, status=400)
            if get_user_model().objects.filter(username=username).exists():
                return Response({"detail": "That driver app username is already in use."}, status=400)
            if not access["account_admin"] and company is None:
                return Response({"detail": "Enter the client company name for this driver."}, status=400)
            driver_user = get_user_model().objects.create_user(username=username, password=password)
            record = Driver.objects.create(
                account=account, name=name, location=str(data.get("location", "")).strip(),
                phone=str(data.get("phone", "")).strip(), company=company, user=driver_user,
            )
            return Response({"id": record.pk, "name": record.name}, status=201)

        if kind == "trucks":
            unit_number = str(data.get("unit_number", "")).strip()
            if not unit_number:
                return Response({"detail": "Enter the truck unit number."}, status=400)
            if not access["account_admin"] and company is None:
                return Response({"detail": "Enter the client company name for this truck."}, status=400)
            try:
                capacity = int(data.get("capacity") or 40000)
            except (TypeError, ValueError):
                return Response({"detail": "Capacity must be a number."}, status=400)
            record = Truck.objects.create(account=account, unit_number=unit_number, capacity=capacity, company=company)
            return Response({"id": record.pk, "name": record.unit_number}, status=201)

        if kind == "trailers":
            number = str(data.get("trailer_number", "")).strip()
            if not number:
                return Response({"detail": "Enter the trailer number."}, status=400)
            if not access["account_admin"] and company is None:
                return Response({"detail": "Enter the client company name for this trailer."}, status=400)
            record = Trailer.objects.create(
                account=account, trailer_number=number, location=str(data.get("location", "")).strip(), company=company,
            )
            return Response({"id": record.pk, "name": record.trailer_number}, status=201)

        customer_name = str(data.get("customer", "")).strip()
        pickup = str(data.get("pickup", "")).strip()
        delivery = str(data.get("delivery", "")).strip()
        if not customer_name or not pickup or not delivery:
            return Response({"detail": "Enter an existing customer, pickup, and delivery location."}, status=400)
        customers = _scoped(Customer.objects.select_related("company"), access, writable=True)
        customer = customers.filter(name__iexact=customer_name).first()
        if customer is None:
            return Response({"detail": "Customer not found. Add the customer first, then create the load."}, status=400)
        record = Load.objects.create(
            account=account, customer=customer, company=customer.company,
            pickup=pickup, delivery=delivery,
            priority=str(data.get("priority", "Normal")) if str(data.get("priority", "Normal")) in {"Low", "Normal", "High", "Critical"} else "Normal",
        )
        return Response({"id": record.pk, "name": f"{record.customer.name} · {record.pickup}"}, status=201)


class MobileLoadActionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, load_id, action):
        access = _access_for(request.user)
        if access is None:
            return Response(
                {"detail": "This user is not assigned to a G Fleet IQ account yet."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not access["can_dispatch"]:
            return Response(
                {"detail": "Your client access is read-only."},
                status=status.HTTP_403_FORBIDDEN,
            )

        queryset = _scoped(
            Load.objects.select_related("customer", "driver", "truck", "trailer", "company"),
            access,
            writable=True,
        )

        with transaction.atomic():
            load = get_object_or_404(queryset.select_for_update(), pk=load_id)
            if action == "assign":
                if load.status != "Available":
                    return Response(
                        {"detail": "Only an available load can be assigned."},
                        status=status.HTTP_409_CONFLICT,
                    )
                driver = select_best_driver(load)
                truck = select_best_truck(load)
                trailer = select_best_trailer(load)
                if not driver or not truck or not trailer:
                    missing = []
                    if not driver:
                        missing.append("driver")
                    if not truck:
                        missing.append("truck")
                    if not trailer:
                        missing.append("trailer")
                    return Response(
                        {"detail": "No available " + ", ".join(missing) + " for this client."},
                        status=status.HTTP_409_CONFLICT,
                    )

                # Lock and recheck the chosen resources so two dispatchers
                # cannot assign the same equipment to separate loads at once.
                driver = Driver.objects.select_for_update().get(pk=driver.pk)
                truck = Truck.objects.select_for_update().get(pk=truck.pk)
                trailer = Trailer.objects.select_for_update().get(pk=trailer.pk)
                if not driver.available or driver.status != "Available":
                    return Response(
                        {"detail": "The selected driver was just assigned. Refresh and try again."},
                        status=status.HTTP_409_CONFLICT,
                    )
                if not truck.active or not trailer.available:
                    return Response(
                        {"detail": "The selected equipment was just assigned. Refresh and try again."},
                        status=status.HTTP_409_CONFLICT,
                    )

                load.driver = driver
                load.truck = truck
                load.trailer = trailer
                load.status = "Assigned"
                load.save(update_fields=["driver", "truck", "trailer", "status"])
                Driver.objects.filter(pk=driver.pk).update(available=False, status="Driving")
                Truck.objects.filter(pk=truck.pk).update(active=False)
                Trailer.objects.filter(pk=trailer.pk).update(available=False)

            elif action == "deliver":
                if load.status != "Assigned":
                    return Response(
                        {"detail": "Only an assigned load can be marked delivered."},
                        status=status.HTTP_409_CONFLICT,
                    )
                load.status = "Delivered"
                load.save(update_fields=["status"])
                if load.driver_id:
                    Driver.objects.filter(
                        pk=load.driver_id,
                        account=access["account"],
                        company_id=load.company_id,
                    ).update(available=True, status="Available")
                if load.truck_id:
                    Truck.objects.filter(
                        pk=load.truck_id,
                        account=access["account"],
                        company_id=load.company_id,
                    ).update(active=True)
                if load.trailer_id:
                    Trailer.objects.filter(
                        pk=load.trailer_id,
                        account=access["account"],
                        company_id=load.company_id,
                    ).update(available=True)
            else:
                return Response({"detail": "Unknown load action."}, status=status.HTTP_404_NOT_FOUND)

            load.refresh_from_db()
            return Response({"load": _load_data(load)})
