"""Read-only searching of available loads within the current fleet account."""
from django import forms
from django.core.paginator import Paginator
from django.shortcuts import render

from fleet.models import Load
from .profit_engine import calculate_load_profit


class LoadSearchForm(forms.Form):
    pickup = forms.CharField(required=False, max_length=200, label="Pickup city or state")
    delivery = forms.CharField(required=False, max_length=200, label="Delivery city or state")
    equipment = forms.CharField(required=False, max_length=50, label="Equipment type")
    pickup_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    max_weight = forms.IntegerField(required=False, min_value=1, label="Maximum weight (lb)")
    sort = forms.ChoiceField(required=False, choices=[("pickup", "Pickup date"), ("rate", "Highest rate")])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field, forms.ChoiceField) else "form-control"


def find_loads(request):
    from .views import _scope_queryset

    form = LoadSearchForm(request.GET)
    loads = _scope_queryset(request, Load, writable=False).filter(status="Available").select_related("customer", "driver")
    if form.is_valid():
        data = form.cleaned_data
        for field, lookup in [("pickup", "pickup__icontains"), ("delivery", "delivery__icontains"), ("equipment", "equipment_type__icontains"), ("pickup_date", "pickup_datetime__date"), ("max_weight", "weight__lte")]:
            if data.get(field):
                loads = loads.filter(**{lookup: data[field]})
        loads = loads.order_by("-rate", "pk") if data.get("sort") == "rate" else loads.order_by("pickup_datetime", "pk")
    else:
        loads = loads.none()
    page = Paginator(loads, 25).get_page(request.GET.get("page"))
    rows = [{"load": load, "estimate": calculate_load_profit(load)} for load in page]
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "dashboard/find_loads.html", {"form": form, "page": page, "rows": rows, "query": query.urlencode()})
