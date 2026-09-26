from django.utils import timezone
from math import radians, sin, cos, sqrt, atan2

from .ai_engine import (
    select_best_driver,
    select_best_truck,
    select_best_trailer,
)

from .route_engine import (
    calculate_route,
    get_road_route,
)
from .profit_engine import calculate_load_profit


# ==========================================================
# DRIVER DISTANCE
# ==========================================================

def calculate_driver_distance(driver, load):
    """
    Calculate approximate straight-line distance between
    the driver's GPS location and the load pickup location.
    """

    if not driver:
        return None

    driver_lat = getattr(driver, "latitude", None)
    driver_lon = getattr(driver, "longitude", None)

    pickup_lat = getattr(load, "pickup_latitude", None)
    pickup_lon = getattr(load, "pickup_longitude", None)

    if None in (
        driver_lat,
        driver_lon,
        pickup_lat,
        pickup_lon,
    ):
        return None

    earth_radius = 3958.8

    lat1 = radians(driver_lat)
    lon1 = radians(driver_lon)

    lat2 = radians(pickup_lat)
    lon2 = radians(pickup_lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    return round(
        earth_radius * c,
        1
    )


# ==========================================================
# AI PLANNING ENGINE
# ==========================================================

def plan_all_loads(loads):

    plans = []

    for load in loads:

        # ==================================================
        # DRIVER
        # ==================================================

        if (
            load.driver
            and load.driver.account_id == load.account_id
            and load.driver.company_id == load.company_id
        ):
            driver = load.driver
        else:
            driver = select_best_driver(load)

        driver_distance = calculate_driver_distance(
            driver,
            load
        )

        # ==================================================
        # EQUIPMENT
        # ==================================================

        truck = select_best_truck(load)
        trailer = select_best_trailer(load)

        # ==================================================
        # ROUTE
        # ==================================================

        route = calculate_route(load)

        # ==================================================
        # PROFIT
        # ==================================================

        profit = calculate_load_profit(load)

        # ==================================================
        # AI EXPLANATIONS
        # ==================================================

        ai_reasons = []

        # ==================================================
        # AI SCORE
        # ==================================================

        ai_score = 0

        # --------------------------------------------------
        # PROFIT PER MILE - 40 POINTS
        # --------------------------------------------------

        profit_per_mile = profit.get(
            "profit_per_mile",
            0
        )

        if profit_per_mile >= 2:
            ai_score += 40
            ai_reasons.append(
                "💰 Excellent Profit Per Mile"
            )

        elif profit_per_mile >= 1.50:
            ai_score += 30
            ai_reasons.append(
                "💰 Strong Profit Per Mile"
            )

        elif profit_per_mile >= 1:
            ai_score += 20
            ai_reasons.append(
                "💰 Positive Profit Per Mile"
            )

        elif profit_per_mile > 0:
            ai_score += 10
            ai_reasons.append(
                "💰 Positive Profit"
            )

        # --------------------------------------------------
        # DRIVER - 15 POINTS
        # --------------------------------------------------

        if driver:

            ai_score += 15

            ai_reasons.append(
                "✅ Driver Available"
            )

            # Driver HOS - 10 points
            if getattr(
                driver,
                "hours_remaining",
                0
            ) >= 8:

                ai_score += 10

                ai_reasons.append(
                    "✅ Driver Has 8+ Hours"
                )

        # --------------------------------------------------
        # DRIVER DISTANCE - 5 POINTS
        # --------------------------------------------------

        if driver_distance is not None:

            if driver_distance <= 25:

                ai_score += 5

                ai_reasons.append(
                    f"📍 Driver {driver_distance} Miles Away"
                )

            elif driver_distance <= 50:

                ai_score += 4

                ai_reasons.append(
                    f"📍 Driver {driver_distance} Miles Away"
                )

            elif driver_distance <= 100:

                ai_score += 2

                ai_reasons.append(
                    f"📍 Driver {driver_distance} Miles Away"
                )

            else:

                ai_reasons.append(
                    f"📍 Driver {driver_distance} Miles Away"
                )

        # --------------------------------------------------
        # TRUCK - 10 POINTS
        # --------------------------------------------------

        if truck:

            ai_score += 10

            ai_reasons.append(
                "✅ Truck Available"
            )

        # --------------------------------------------------
        # TRAILER - 10 POINTS
        # --------------------------------------------------

        if trailer:

            ai_score += 10

            ai_reasons.append(
                "✅ Trailer Available"
            )

        # --------------------------------------------------
        # ROUTE - 5 POINTS
        # --------------------------------------------------

        if route.get(
            "miles",
            0
        ) > 0:

            ai_score += 5

            ai_reasons.append(
                "🛣️ Route Calculated"
            )

        # ==================================================
        # LOAD PRIORITY - 5 POINTS
        # ==================================================

        priority = getattr(
            load,
            "priority",
            "Normal"
        )

        if priority == "Critical":

            ai_score += 5

            ai_reasons.append(
                "🔴 Critical Priority"
            )

        elif priority == "High":

            ai_score += 4

            ai_reasons.append(
                "🟠 High Priority"
            )

        elif priority == "Normal":

            ai_score += 2

            ai_reasons.append(
                "🟡 Normal Priority"
            )

        elif priority == "Low":

            ai_score += 1

            ai_reasons.append(
                "🟢 Low Priority"
            )

        # ==================================================
        # PICKUP TIMING - 5 POINTS
        # ==================================================

        if load.pickup_datetime:

            now = timezone.now()

            pickup_time = load.pickup_datetime

            if timezone.is_naive(
                pickup_time
            ):
                pickup_time = timezone.make_aware(
                    pickup_time
                )

            hours_until_pickup = (
                pickup_time - now
            ).total_seconds() / 3600

            if hours_until_pickup <= 6:

                ai_score += 5

                ai_reasons.append(
                    "⏰ Pickup Within 6 Hours"
                )

            elif hours_until_pickup <= 12:

                ai_score += 4

                ai_reasons.append(
                    "⏰ Pickup Within 12 Hours"
                )

            elif hours_until_pickup <= 24:

                ai_score += 3

                ai_reasons.append(
                    "📅 Pickup Within 24 Hours"
                )

            elif hours_until_pickup <= 48:

                ai_score += 2

                ai_reasons.append(
                    "📅 Pickup Within 48 Hours"
                )

            else:

                ai_score += 1

                ai_reasons.append(
                    "📅 Pickup Scheduled"
                )

        # ==================================================
        # KEEP SCORE BETWEEN 0 AND 100
        # ==================================================

        ai_score = min(
            max(ai_score, 0),
            100
        )
                # ==================================================
        # DRIVER → PICKUP ROAD ROUTE
        # ==================================================

        driver_route = get_road_route(
            getattr(driver, "latitude", None),
            getattr(driver, "longitude", None),
            getattr(load, "pickup_latitude", None),
            getattr(load, "pickup_longitude", None),
        )

        if driver_route:
            driver_road_miles = driver_route["miles"]
            driver_drive_hours = driver_route["drive_hours"]

        elif driver_distance is not None:
            driver_road_miles = driver_distance
            driver_drive_hours = round(
                driver_distance / 60,
                1,
            )

        else:
            driver_road_miles = None
            driver_drive_hours = None

               # ==================================================
        # ADD PLAN
        # ==================================================

        plans.append({
            "load": load,
            "driver": driver,
            "driver_distance": driver_distance,
            "driver_road_miles": driver_road_miles,
            "driver_drive_hours": driver_drive_hours,
            "truck": truck,
            "trailer": trailer,
            "route": route,
            "profit": profit,
            "ai_reasons": ai_reasons,
            "ai_score": ai_score,
        })

    # ======================================================
    # RANK LOADS BY AI SCORE
    # ======================================================

    plans.sort(
        key=lambda plan: plan.get(
            "ai_score",
            0
        ),
        reverse=True,
    )

    return plans
