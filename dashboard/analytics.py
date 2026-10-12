import logging
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from fleet.models import Company, FleetAccount
from .models import DailyActivity, DailyVisit

logger = logging.getLogger(__name__)
COOKIE = "gfiq_visitor"


def can_view_analytics(user):
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or settings.PLATFORM_ANALYTICS_USERS.get(str(user.pk)) == user.username))


class VisitTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.can_view_analytics = can_view_analytics(request.user)
        response = self.get_response(request)
        # Only rendered pages, excluding admin traffic, known bots, and prefetches.
        if (request.method != "GET" or response.status_code != 200
                or "text/html" not in response.get("Content-Type", "")
                or request.path.startswith(("/admin/", "/owner/", "/static/", "/api/"))
                or request.can_view_analytics
                or request.headers.get("Purpose") == "prefetch"
                or any(word in request.headers.get("User-Agent", "").lower()
                       for word in ("bot", "crawler", "spider", "headless"))):
            return response
        raw_id = request.get_signed_cookie(COOKIE, default=None, salt=COOKIE)
        try:
            visitor_id = uuid.UUID(raw_id) if raw_id else uuid.uuid4()
        except (ValueError, TypeError, AttributeError):
            visitor_id = uuid.uuid4()
        user = request.user if request.user.is_authenticated else None
        day = timezone.localdate()
        try:
            visit, created = DailyVisit.objects.get_or_create(
                visitor_id=visitor_id, day=day, defaults={"user": user})
            if user:
                if not created and visit.user_id is None:
                    DailyVisit.objects.filter(pk=visit.pk, user__isnull=True).update(user=user)
                DailyActivity.objects.get_or_create(user=user, day=day)
        except DatabaseError:
            # Analytics availability must never prevent customers using the app.
            logger.exception("Could not record daily app activity")
            return response
        if not raw_id or str(visitor_id) != raw_id:
            response.set_signed_cookie(COOKIE, str(visitor_id), salt=COOKIE,
                                       max_age=365 * 24 * 60 * 60, httponly=True,
                                       secure=request.is_secure(), samesite="Lax")
        return response


@login_required
@never_cache
def owner_analytics(request):
    # Customer workspace owners must not see another customer's data.
    if not can_view_analytics(request.user):
        return HttpResponseForbidden("Only the platform administrator can view app analytics.")
    try:
        days = int(request.GET.get("days", "7"))
    except ValueError:
        days = 7
    if days not in (1, 7, 30, 90):
        days = 7
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    visits = DailyVisit.objects.filter(day__range=(start, today))
    users = get_user_model().objects.filter(is_superuser=False)
    for user_id, username in settings.PLATFORM_ANALYTICS_USERS.items():
        if user_id.isdigit():
            users = users.exclude(pk=int(user_id), username=username)
    activity = DailyActivity.objects.filter(day__range=(start, today), user__in=users)
    registrations = users.filter(date_joined__date__range=(start, today))
    workspaces = FleetAccount.objects.all()
    daily_visits = dict(visits.values("day").annotate(n=Count("visitor_id", distinct=True)).values_list("day", "n"))
    daily_active = dict(activity.values("day").annotate(n=Count("user_id", distinct=True)).values_list("day", "n"))
    rows = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        rows.append({"day": day, "visitors": daily_visits.get(day, 0), "active": daily_active.get(day, 0)})
    return render(request, "dashboard/owner_analytics.html", {
        "days": days, "periods": (1, 7, 30, 90), "start": start, "today": today,
        "visitors": visits.values("visitor_id").distinct().count(),
        "active_users": activity.values("user_id").distinct().count(),
        "new_accounts": registrations.count(), "total_accounts": users.count(),
        "total_workspaces": workspaces.count(), "total_companies": Company.objects.count(),
        "new_workspaces": workspaces.filter(created_at__date__range=(start, today)).count(),
        "recent_workspaces": workspaces.order_by("-created_at")[:20], "rows": rows,
        "tracking_since": DailyVisit.objects.order_by("first_seen").values_list("first_seen", flat=True).first(),
    })
