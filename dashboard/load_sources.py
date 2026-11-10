"""Official external portals; authentication stays with each provider."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET


LOAD_SOURCES = (
    {"name": "DAT One", "kind": "Load board", "domain": "one.dat.com", "login_url": "https://one.dat.com/", "register_url": "https://www.dat.com/dat-solutions"},
    {"name": "Truckstop", "kind": "Load board", "domain": "app.truckstop.com", "login_url": "https://app.truckstop.com/", "register_url": "https://checkout.truckstop.com/"},
    {"name": "123Loadboard", "kind": "Load board", "domain": "123loadboard.com", "login_url": "https://www.123loadboard.com/login/", "register_url": "https://www.123loadboard.com/signup/"},
    {"name": "Direct Freight", "kind": "Load board", "domain": "directfreight.com", "login_url": "https://www.directfreight.com/home/user/login", "register_url": "https://www.directfreight.com/home/user/compare"},
    {"name": "C.H. Robinson / Navisphere Carrier", "kind": "Broker portal", "domain": "navispherecarrier.com", "login_url": "https://www.navispherecarrier.com/login", "register_url": "https://www.chrobinson.com/carriers/become-a-carrier/"},
    {"name": "Uber Freight", "kind": "Broker portal", "domain": "uberfreight.com", "login_url": "https://www.uberfreight.com/en-US/login", "register_url": "https://freightbonjour.uber.com/onboarding-start"},
    {"name": "RXO Connect", "kind": "Broker portal", "domain": "carrier.rxoconnect.rxo.com", "login_url": "https://carrier.rxoconnect.rxo.com/", "register_url": "https://rxo.com/carriers/carrier-registration-form/"},
    {"name": "TQL Carrier Dashboard", "kind": "Broker portal", "domain": "carrierdashboard.tql.com", "login_url": "https://carrierdashboard.tql.com/", "register_url": "https://register.tql.com/"},
)


@login_required
@require_GET
def load_sources(request):
    return render(request, "dashboard/load_sources.html", {"load_sources": LOAD_SOURCES})
