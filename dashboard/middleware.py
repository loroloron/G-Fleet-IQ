from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from fleet.models import AccountMembership, Company, CompanyMembership


class RequireLoginMiddleware:
    """Require a signed-in user for fleet pages while keeping entry points public."""

    PUBLIC_URLS = {"landing", "login", "logout", "sign_up", "set_language"}
    OWNER_ONLY_URLS = {"account_team"}
    ADMIN_MANAGEMENT_URLS = {"companies", "edit_company"}
    VIEWER_BLOCKED_URLS = {"assign_load", "plan_all_loads", "dispatch_recommended_load"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match and (match.url_name in self.PUBLIC_URLS or match.app_name == "admin"):
            return None
        static_prefix = "/" + settings.STATIC_URL.lstrip("/")
        if request.path.startswith(static_prefix):
            return None
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        account_membership = (
            AccountMembership.objects.filter(user=request.user, active=True)
            .select_related("account")
            .first()
        )
        client_memberships = list(
            CompanyMembership.objects.filter(user=request.user, active=True)
            .select_related("company", "company__account")
        )
        request.account_membership = account_membership
        request.company_memberships = client_memberships
        request.is_account_admin = bool(account_membership)
        request.account = (
            account_membership.account
            if account_membership
            else (client_memberships[0].company.account if client_memberships else None)
        )
        request.allowed_company_ids = {
            item.company_id for item in client_memberships
        }
        request.write_company_ids = {
            item.company_id
            for item in client_memberships
            if item.role in {CompanyMembership.ROLE_CLIENT_ADMIN, CompanyMembership.ROLE_DISPATCHER}
        }

        # Users without a membership must be able to submit account_setup to
        # claim the first-owner role; otherwise this middleware redirects the
        # setup POST back to the same page before the view can process it.
        if match and match.url_name == "account_setup":
            return None

        if not request.account:
            return redirect("account_setup")

        if not request.is_account_admin and not client_memberships:
            return redirect("account_setup")

        role = account_membership.role if account_membership else None
        if not request.is_account_admin and request.method == "POST" and not request.write_company_ids:
            return HttpResponseForbidden("This client account has read-only access.")
        if not request.is_account_admin and match and match.url_name in self.VIEWER_BLOCKED_URLS and not request.write_company_ids:
            return HttpResponseForbidden("This client account has read-only access.")

        if match and match.url_name in self.OWNER_ONLY_URLS:
            if not account_membership or role != AccountMembership.ROLE_OWNER:
                return HttpResponseForbidden("Only the G Fleet IQ account owner can manage account administrators.")

        if match and match.url_name in self.ADMIN_MANAGEMENT_URLS:
            if not request.is_account_admin:
                return HttpResponseForbidden("Only the account owner or an administrator can manage client companies.")

        if match and match.url_name == "client_team":
            company = Company.objects.filter(
                pk=view_kwargs.get("company_id"),
                account=request.account,
            ).first()
            request.client_team_company = company
            if not company:
                return HttpResponseForbidden("That client company is not part of this G Fleet IQ account.")
            if not request.is_account_admin:
                company_membership = next(
                    (item for item in client_memberships if item.company_id == company.id),
                    None,
                )
                if not company_membership or company_membership.role != CompanyMembership.ROLE_CLIENT_ADMIN:
                    return HttpResponseForbidden("Only this client’s administrator can manage its dispatchers.")
        return None
