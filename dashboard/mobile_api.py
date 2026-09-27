from django.db import transaction
from django.shortcuts import get_object_or_404
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
    CompanyMembership,
    Driver,
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
        token, _ = Token.objects.get_or_create(user=user)
        access = _access_for(user)
        return Response({
            "token": token.key,
            "user": {"username": user.get_username()},
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
