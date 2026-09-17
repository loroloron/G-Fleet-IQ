from urllib import request
from django.http import HttpResponse

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Avg, Sum

from fleet.models import (
    Company,
    Customer,
    Driver,
    Truck,
    Trailer,
    Load,
)

from .forms import (
    CompanyForm,
    CustomerForm,
    DriverForm,
    TruckForm,
    TrailerForm,
    LoadForm,
)

from .fuel_engine import find_best_fuel_stop

from .ai_engine import (
    select_best_driver,
    select_best_truck,
    select_best_trailer,
)

from .geocode_engine import geocode_address
from .planning_engine import plan_all_loads as build_plans
from .planning_engine import calculate_driver_distance
from .route_engine import calculate_route
from .profit_engine import (
    calculate_load_profit,
     
)

def home(request):
    all_loads = list(Load.objects.all().select_related("driver"))
    total_revenue = 0
    total_profit = 0

    for load in all_loads:
        result = calculate_load_profit(load)
        total_revenue += result["revenue"]
        total_profit += result["profit"]
    # ======================================================
    # DASHBOARD CONTEXT
    # ======================================================
    context = {
        "drivers": Driver.objects.count(),
        "trucks": Truck.objects.count(),
        "trailers": Trailer.objects.count(),
        "loads": Load.objects.count(),
        "customers": Customer.objects.count(),

        "available_drivers": Driver.objects.filter(
            available=True
        ).count(),

        "available_trucks": Truck.objects.filter(
            active=True
        ).count(),

        "available_trailers": Trailer.objects.filter(
            available=True
        ).count(),

        "available_loads": Load.objects.filter(
            status="Available"
        ).count(),

        "active_loads": Load.objects.filter(
            status="Assigned"
        ).count(),

        "recent_drivers": Driver.objects.order_by(
            "-id"
        )[:5],

        "recent_trucks": Truck.objects.order_by(
            "-id"
        )[:5],

        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "average_profit": average_profit,
    }

    return render(
        request,
        "dashboard/home.html",
        context,
    )
   

   


# ==========================================================
# DRIVERS
# ==========================================================

def drivers(request):
    return render(
        request,
        "dashboard/drivers.html",
        {"drivers": Driver.objects.all()},
    )


def add_driver(request):
    form = DriverForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        driver = form.save(commit=False)

        location_result = geocode_address(driver.location)
        if location_result:
            driver.latitude = location_result["latitude"]
            driver.longitude = location_result["longitude"]

        driver.save()
        return redirect("drivers")

    return render(
        request,
        "dashboard/add_driver.html",
        {"form": form},
    )


def edit_driver(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)

    form = DriverForm(
        request.POST or None,
        instance=driver,
    )

    if request.method == "POST" and form.is_valid():
        driver = form.save(commit=False)

        location_result = geocode_address(driver.location)
        if location_result:
            driver.latitude = location_result["latitude"]
            driver.longitude = location_result["longitude"]

        driver.save()
        return redirect("drivers")

    return render(
        request,
        "dashboard/edit_driver.html",
        {
            "driver": driver,
            "form": form,
        },
    )


def delete_driver(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)

    if request.method == "POST":
        driver.delete()
        return redirect("drivers")

    return render(
        request,
        "dashboard/delete_driver.html",
        {"driver": driver},
    )


# ==========================================================
# CUSTOMERS
# ==========================================================

def customers(request):
    if request.method == "POST":
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("customers")
    else:
        form = CustomerForm()

    return render(
        request,
        "dashboard/customers.html",
        {
            "customers": Customer.objects.all(),
            "form": form,
        },
    )


def delete_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == "POST":
        customer.delete()
        return redirect("customers")

    return render(
        request,
        "dashboard/delete_customer.html",
        {"customer": customer},
    )


# ==========================================================
# TRUCKS
# ==========================================================

def trucks(request):
    return render(
        request,
        "dashboard/trucks.html",
        {"trucks": Truck.objects.all()},
    )


def add_truck(request):
    form = TruckForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("trucks")

    return render(
        request,
        "dashboard/add_truck.html",
        {"form": form},
    )


def edit_truck(request, truck_id):
    truck = get_object_or_404(Truck, id=truck_id)

    form = TruckForm(
        request.POST or None,
        instance=truck,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("trucks")

    return render(
        request,
        "dashboard/edit_truck.html",
        {
            "truck": truck,
            "form": form,
        },
    )


def delete_truck(request, truck_id):
    truck = get_object_or_404(Truck, id=truck_id)

    if request.method == "POST":
        truck.delete()
        return redirect("trucks")

    return render(
        request,
        "dashboard/delete_truck.html",
        {"truck": truck},
    )


# ==========================================================
# TRAILERS
# ==========================================================

def trailers(request):
    return render(
        request,
        "dashboard/trailers.html",
        {"trailers": Trailer.objects.all()},
    )


def add_trailer(request):
    form = TrailerForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("trailers")

    return render(
        request,
        "dashboard/add_trailer.html",
        {"form": form},
    )


def edit_trailer(request, trailer_id):
    trailer = get_object_or_404(Trailer, id=trailer_id)

    form = TrailerForm(
        request.POST or None,
        instance=trailer,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("trailers")

    return render(
        request,
        "dashboard/edit_trailer.html",
        {
            "trailer": trailer,
            "form": form,
        },
    )


def delete_trailer(request, trailer_id):
    trailer = get_object_or_404(Trailer, id=trailer_id)

    if request.method == "POST":
        trailer.delete()
        return redirect("trailers")

    return render(
        request,
        "dashboard/delete_trailer.html",
        {"trailer": trailer},
    )


# ==========================================================
# LOADS
# ==========================================================

def loads(request):
    if request.method == "POST":
        form = LoadForm(request.POST)

        if form.is_valid():
            load = form.save(commit=False)

            pickup_result = geocode_address(load.pickup)
            delivery_result = geocode_address(load.delivery)

            if pickup_result:
                load.pickup_latitude = pickup_result["latitude"]
                load.pickup_longitude = pickup_result["longitude"]

            if delivery_result:
                load.delivery_latitude = delivery_result["latitude"]
                load.delivery_longitude = delivery_result["longitude"]

            load.save()
            return redirect("loads")
    else:
        form = LoadForm()

    return render(
        request,
        "dashboard/loads.html",
        {
            "loads": Load.objects.all(),
            "form": form,
        },
    )


def delete_load(request, load_id):
    load = get_object_or_404(Load, id=load_id)

    if request.method == "POST":
        load.delete()
        return redirect("loads")

    return render(
        request,
        "dashboard/delete_load.html",
        {"load": load},
    )


# ==========================================================
# AI DISPATCH
# ==========================================================

def ai_dispatch(request):
    available_drivers = (
        Driver.objects.filter(
            available=True,
            status="Available",
        )
        .order_by("-ai_score", "-hours_remaining")
    )

    available_trucks = Truck.objects.filter(
        active=True
    ).order_by("-capacity")

    available_trailers = Trailer.objects.filter(
        available=True
    ).order_by("-capacity")

    available_loads = Load.objects.filter(
        status="Available"
    ).order_by(
        "-priority",
        "pickup_datetime",
    )

    best_load = available_loads.first()

    best_driver = (
        select_best_driver(best_load)
        if best_load
        else None
    )

    best_truck = (
        select_best_truck(best_load)
        if best_load
        else None
    )

    best_trailer = (
        select_best_trailer(best_load)
        if best_load
        else None
    )

    route = (
        calculate_route(best_load)
        if best_load
        else None
    )

    ai_score = 0
    ai_reasons = []

    if best_driver:
        ai_score += 25
        ai_reasons.append("✔ Best Driver Available")

        if getattr(best_driver, "hours_remaining", 0) > 0:
            ai_score += 15
            ai_reasons.append("✔ Driver Has Hours Available")

    if best_truck:
        ai_score += 20
        ai_reasons.append("✔ Truck Available")

    if best_trailer:
        ai_score += 20
        ai_reasons.append("✔ Trailer Available")

    if best_load:
        ai_score += 20
        ai_reasons.append("✔ Load Ready")

        if getattr(best_load, "priority", "") == "High":
            ai_score += 10
            ai_reasons.append("✔ High Priority Load")

    ai_score = min(ai_score, 100)
    driver_to_pickup_miles = None
    driver_pickup_eta = None
    best_fuel_stop = None

    context = {
        "drivers": available_drivers,
        "trucks": available_trucks,
        "trailers": available_trailers,
        "loads": available_loads,
        "best_driver": best_driver,
        "best_truck": best_truck,
        "best_trailer": best_trailer,
        "best_load": best_load,
        "route": route,
        "ai_score": ai_score,
        "ai_reasons": ai_reasons,
        "driver_to_pickup_miles": driver_to_pickup_miles,
        "driver_pickup_eta": driver_pickup_eta,
        "best_fuel_stop": best_fuel_stop,
    }

    return render(
        request,
        "dashboard/ai_dispatch.html",
        context,
    )


# ==========================================================
# DISPATCH BOARD
# ==========================================================

def dispatch_board(request):

    available_drivers = Driver.objects.filter(
        available=True,
        status="Available",
    )

    for driver in available_drivers:

        score = 0

        if driver.available:
            score += 40

        if getattr(driver, "hours_remaining", 0) >= 8:
            score += 30

        elif getattr(driver, "hours_remaining", 0) >= 4:
            score += 20

        else:
            score += 10

        if getattr(driver, "truck", None):
            score += 20

        driver.ai_score = score

        driver.save(
            update_fields=["ai_score"]
        )

    # ==========================================================
    # AI PLANS
    # ==========================================================

    all_loads = Load.objects.filter(
        status="Available"
    )

    plans = build_plans(
        all_loads
    )

    best_plan = (
        plans[0]
        if plans
        else None
    )

    # ==========================================================
    # DEFAULT VALUES
    # ==========================================================

    driver_to_pickup_miles = None
    driver_pickup_eta = None
    best_fuel_stop = None

    # ==========================================================
    # AI FUEL SOLUTION
    # ==========================================================

    if best_plan:

        fuel_mpg = (
            best_plan["profit"].get(
                "mpg",
                7.0,
            )
        )

        trip_miles = (
            best_plan["route"].get(
                "miles",
                0,
            )
        )

        # ------------------------------------------------------
        # TEST DIESEL STATIONS
        # ------------------------------------------------------

        test_stations = [
            {
                "brand": "Pilot",
                "name": "Pilot Travel Center",
                "address": "Route Stop A",
                "price_per_gallon": 3.20,
                "detour_miles": 0.6,
            },
            {
                "brand": "Love's",
                "name": "Love's Travel Stop",
                "address": "Route Stop B",
                "price_per_gallon": 3.25,
                "detour_miles": 0.5,
            },
            {
                "brand": "TA",
                "name": "TA Travel Center",
                "address": "Route Stop C",
                "price_per_gallon": 3.27,
                "detour_miles": 0.7,
            },
            {
                "brand": "QuikTrip",
                "name": "QuikTrip",
                "address": "Route Stop D",
                "price_per_gallon": 3.18,
                "detour_miles": 0.4,
            },
        ]

        best_fuel_stop = find_best_fuel_stop(
            test_stations,
            trip_miles,
            fuel_mpg,
        )

        # ======================================================
        # DRIVER → PICKUP
        # ======================================================

        driver = best_plan.get("driver")
        load = best_plan.get("load")

        if driver and load:
            driver_to_pickup_miles = (
                best_plan.get("driver_road_miles")
                or best_plan.get("driver_distance")
            )

            if driver_to_pickup_miles is None:
                driver_to_pickup_miles = calculate_driver_distance(
                    driver,
                    load,
                )

            if driver_to_pickup_miles is not None:
                driver_pickup_eta = round(
                    driver_to_pickup_miles / 60,
                    1,
                )

    # =========================================================
    # RECOMMENDATIONS
    # =========================================================

    recommended_driver = (
        available_drivers
        .order_by("-ai_score")
        .first()
    )

    recommended_truck = (
        Truck.objects
        .filter(active=True)
        .first()
    )

    recommended_trailer = (
        Trailer.objects
        .filter(available=True)
        .first()
    )

    # ==========================================================
    # CONTEXT
    # ==========================================================

    context = {
        "loads": Load.objects.all(),
        "drivers": available_drivers,
        "trucks": Truck.objects.all(),
        "trailers": Trailer.objects.all(),
        "plans": plans,
        "best_plan": best_plan,
        "best_fuel_stop": best_fuel_stop,
        "driver_to_pickup_miles": driver_to_pickup_miles,
        "driver_pickup_eta": driver_pickup_eta,
        "recommended_driver": recommended_driver,
        "recommended_truck": recommended_truck,
        "recommended_trailer": recommended_trailer,
    }
    return render(
        request,
        "dashboard/dispatch_board.html",
        context,
    )

# ==========================================================
# ASSIGN LOAD
# ==========================================================

def assign_load(request, load_id):

    load = get_object_or_404(
        Load,
        id=load_id,
    )

    driver = select_best_driver(load)
    truck = select_best_truck(load)
    trailer = select_best_trailer(load)

    if not driver:
        messages.error(
            request,
            "❌ Dispatch failed: No available driver."
        )
        return redirect("dispatch_board")

    if not truck:
        messages.error(
            request,
            "❌ Dispatch failed: No available truck."
        )
        return redirect("dispatch_board")

    if not trailer:
        messages.error(
            request,
            "❌ Dispatch failed: No available trailer."
        )
        return redirect("dispatch_board")

    load.driver = driver
    load.truck = truck
    load.trailer = trailer
    load.status = "Assigned"

    driver.available = False
    driver.status = "Driving"

    truck.active = False
    trailer.available = False

    load.save()
    driver.save()
    truck.save()
    trailer.save()

    messages.success(
        request,
        f"✅ Load {load.id} dispatched successfully! "
        f"Driver: {driver.name} | "
        f"Truck: {truck.unit_number} | "
        f"Trailer: {trailer.trailer_number}"
    )

    return redirect("dispatch_board")

# ==========================================================
# PLAN ALL LOADS
# ==========================================================

def plan_all_loads(request):
    loads_to_plan = Load.objects.filter(status="Available")

    for load in loads_to_plan:
        driver = select_best_driver(load)
        truck = select_best_truck(load)
        trailer = select_best_trailer(load)

        if driver and truck and trailer:
            load.driver = driver
            load.truck = truck
            load.trailer = trailer
            load.status = "Assigned"

            driver.available = False
            driver.status = "Driving"

            truck.active = False
            trailer.available = False

            load.save()
            driver.save()
            truck.save()
            trailer.save()

    return redirect("dispatch_board")


# ==========================================================
# DISPATCH RECOMMENDED LOAD
# ==========================================================

def dispatch_recommended_load(request):
    if request.method != "POST":
        return redirect("dispatch_board")

    plans = build_plans(Load.objects.all())

    if not plans:
        return redirect("dispatch_board")

    best_plan = plans[0]

    load = best_plan["load"]
    driver = best_plan["driver"]
    truck = best_plan["truck"]
    trailer = best_plan["trailer"]

    if not driver or not truck or not trailer:
        return redirect("dispatch_board")

    load.driver = driver
    load.truck = truck
    load.trailer = trailer
    load.status = "Assigned"

    driver.available = False
    driver.status = "Driving"

    truck.active = False
    trailer.available = False

    load.save()
    driver.save()
    truck.save()
    trailer.save()

    return redirect("dispatch_board")


# ==========================================================
# COMPANIES
# ==========================================================

def companies(request):
    if request.method == "POST":
        form = CompanyForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("companies")
    else:
        form = CompanyForm()

    return render(
        request,
        "dashboard/companies.html",
        {
            "companies": Company.objects.all(),
            "form": form,
        },
    )


# ==========================================================
# FLEET MAP
# ==========================================================

def fleet_map(request):
    trucks = Truck.objects.filter(active=True)

    return render(
        request,
        "dashboard/fleet_map.html",
        {"trucks": trucks},
    )


# ==========================================================
# TRUCK DETAIL
# ==========================================================

def truck_detail(request, truck_id):
    truck = get_object_or_404(Truck, id=truck_id)

    return render(
        request,
        "dashboard/truck_detail.html",
        {"truck": truck},
    )
   