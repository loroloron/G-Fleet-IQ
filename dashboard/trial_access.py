"""Enforce trial expiry for token-authenticated mobile endpoints as well as web."""
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import PermissionDenied
from fleet.models import AccountMembership, CompanyMembership, Driver


class TrialTokenAuthentication(TokenAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        membership = AccountMembership.objects.filter(user=user, active=True).select_related("account").first()
        account = membership.account if membership else None
        if account is None:
            client = CompanyMembership.objects.filter(user=user, active=True).select_related("company__account").first()
            account = client.company.account if client else None
        if account is None:
            driver = Driver.objects.filter(user=user).select_related("account").first()
            account = driver.account if driver else None
        if account and account.trial_expired:
            raise PermissionDenied("Your 14-day free trial has ended. Contact G Fleet IQ to continue.", code="trial_expired")
        return result
