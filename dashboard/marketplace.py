"""Opt-in freight marketplace, kept separate from private dispatch data."""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from fleet.models import Company, FreightPosting
from .load_search import LoadSearchForm


def manageable_postings(request):
    postings = FreightPosting.objects.filter(account=request.account)
    if request.is_account_admin:
        return postings
    return postings.filter(company_id__in=request.write_company_ids)


def live_postings():
    today = timezone.localdate()
    return FreightPosting.objects.filter(status="open", expires_on__gte=today, pickup_date__gte=today)


class PostingForm(forms.ModelForm):
    company = forms.ModelChoiceField(queryset=Company.objects.none(), required=False, label="Publish for")
    weight = forms.IntegerField(min_value=1, max_value=2147483647, label="Weight (lb)")
    rate = forms.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2, label="Total offered rate ($), optional")
    share_confirmation = forms.BooleanField(label="Publish this freight and its contact details to all signed-in G Fleet IQ marketplace customers.")

    class Meta:
        model = FreightPosting
        fields = ["company", "business_name", "business_type", "contact_name", "contact_email", "contact_phone", "pickup", "delivery", "pickup_date", "equipment_type", "weight", "rate", "expires_on", "notes"]
        widgets = {
            "pickup_date": forms.DateInput(attrs={"type": "date"}),
            "expires_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        companies = Company.objects.filter(account=request.account, active=True)
        if not request.is_account_admin:
            companies = companies.filter(pk__in=request.write_company_ids)
            self.fields["company"].required = True
        self.fields["company"].queryset = companies.order_by("name")
        self.fields["company"].empty_label = "My account"
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if name == "share_confirmation" else "form-select" if isinstance(field.widget, forms.Select) else "form-control"

    def clean(self):
        data = super().clean()
        today = timezone.localdate()
        for name in ("pickup_date", "expires_on"):
            if data.get(name) and data[name] < today:
                self.add_error(name, "Choose today or a future date.")
        if data.get("pickup_date") and data.get("expires_on") and data["expires_on"] > data["pickup_date"]:
            self.add_error("expires_on", "The listing must expire on or before the pickup date.")
        return data


@login_required
@require_GET
def marketplace(request):
    form = LoadSearchForm(request.GET)
    mine = request.GET.get("mine") == "1"
    postings = manageable_postings(request) if mine else live_postings()
    if form.is_valid():
        data = form.cleaned_data
        for name, lookup in [("pickup", "pickup__icontains"), ("delivery", "delivery__icontains"), ("equipment", "equipment_type__icontains"), ("pickup_date", "pickup_date"), ("max_weight", "weight__lte")]:
            if data.get(name):
                postings = postings.filter(**{lookup: data[name]})
        # Explicit null ordering keeps unquoted rates after quoted rates on PostgreSQL.
        postings = postings.order_by(F("rate").desc(nulls_last=True), "pk") if data.get("sort") == "rate" else postings.order_by("pickup_date", "pk")
    else:
        postings = postings.none()
    page = Paginator(postings, 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "dashboard/marketplace.html", {
        "form": form, "page": page, "query": query.urlencode(), "mine": mine,
        "can_post": request.is_account_admin or bool(request.write_company_ids),
    })


@login_required
@require_http_methods(["GET", "POST"])
def post_freight(request):
    if not request.is_account_admin and not request.write_company_ids:
        return HttpResponseForbidden("Your role can browse freight but cannot publish it.")
    form = PostingForm(request.POST if request.method == "POST" else None, request=request)
    if request.method == "POST" and form.is_valid():
        posting = form.save(commit=False)
        posting.account = request.account
        posting.created_by = request.user
        posting.save()
        messages.success(request, "Freight published to the marketplace.")
        return redirect("freight_detail", posting_id=posting.pk)
    return render(request, "dashboard/post_freight.html", {"form": form})


@login_required
@require_GET
def freight_detail(request, posting_id):
    owned = manageable_postings(request).filter(pk=posting_id).exists()
    posting = get_object_or_404(FreightPosting.objects.filter(Q(pk__in=live_postings().values("pk")) | Q(pk__in=manageable_postings(request).values("pk"))), pk=posting_id)
    return render(request, "dashboard/freight_detail.html", {"posting": posting, "can_close": owned, "is_live": live_postings().filter(pk=posting.pk).exists()})


@login_required
@require_POST
def close_freight(request, posting_id):
    posting = get_object_or_404(manageable_postings(request), pk=posting_id)
    posting.status = "closed"
    posting.save(update_fields=["status", "updated_at"])
    messages.success(request, "Freight closed and removed from marketplace search.")
    return redirect("marketplace")
