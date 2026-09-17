from decimal import Decimal, InvalidOperation


def to_decimal(value, default="0"):
    """
    Safely convert numbers, empty values, or None into Decimal.
    """
    if value in (None, ""):
        return Decimal(default)

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def calculate_load_profit(load):

    revenue = to_decimal(
        getattr(load, "rate", 0)
    )

    miles = to_decimal(
        getattr(load, "miles", 0)
    )

    if miles <= 0:
        miles = to_decimal(
            getattr(load, "distance", 0)
        )

    # ======================================================
    # FUEL
    # ======================================================

    driver = getattr(load, "driver", None)

    driver_mpg = getattr(
        driver,
        "fuel_efficiency",
        None,
    )

    mpg = to_decimal(driver_mpg, "7.0")

    if mpg <= 0:
        mpg = Decimal("7.0")

    fuel_price = Decimal("3.75")

    if miles > 0:
        gallons = miles / mpg
        fuel_cost = gallons * fuel_price
    else:
        gallons = Decimal("0")
        fuel_cost = Decimal("0")

    # ======================================================
    # OTHER EXPENSES
    # ======================================================

    driver_pay = to_decimal(
        getattr(load, "driver_pay", 0)
    )

    tolls = to_decimal(
        getattr(load, "tolls", 0)
    )

    maintenance_cost = to_decimal(
        getattr(load, "maintenance_cost", 0)
    )

    insurance_cost = to_decimal(
        getattr(load, "insurance_cost", 0)
    )

    total_expenses = (
        fuel_cost
        + driver_pay
        + tolls
        + maintenance_cost
        + insurance_cost
    )

    # ======================================================
    # PROFIT
    # ======================================================

    profit = revenue - total_expenses

    if miles > 0:
        profit_per_mile = profit / miles
    else:
        profit_per_mile = Decimal("0")

    return {
        "revenue": revenue,
        "miles": miles,
        "mpg": mpg,
        "gallons": gallons,
        "fuel_price": fuel_price,
        "fuel_cost": fuel_cost,
        "driver_pay": driver_pay,
        "tolls": tolls,
        "maintenance_cost": maintenance_cost,
        "insurance_cost": insurance_cost,
        "total_expenses": total_expenses,
        "profit": profit,
        "profit_per_mile": profit_per_mile,
    }
def save_load_profit(load):

    result = calculate_load_profit(load)

    load.fuel_cost = result["fuel_cost"]
    load.profit = result["profit"]
    load.profit_per_mile = result["profit_per_mile"]

    load.save(
        update_fields=[
            "fuel_cost",
            "profit",
            "profit_per_mile",
        ]
    )

    return result
