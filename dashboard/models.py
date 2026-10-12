from django.db import models
from django.conf import settings

class DailyVisit(models.Model):
    """One browser per local day; no IP, query string, or browsing history."""

    visitor_id = models.UUIDField()
    day = models.DateField(db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL)
    first_seen = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["visitor_id", "day"],
                                               name="unique_daily_browser_visit")]


class DailyActivity(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    day = models.DateField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "day"],
                                               name="unique_daily_active_user")]
