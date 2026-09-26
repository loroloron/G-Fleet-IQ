from fleet.models import Driver, Truck, Trailer


def select_best_driver(load):
    return (
        Driver.objects.filter(
            account=load.account,
            company_id=load.company_id,
            available=True,
            status="Available"
        )
        .order_by("-ai_score", "-hours_remaining")
        .first()
    )


def select_best_truck(load):
    return (
        Truck.objects.filter(
            account=load.account,
            company_id=load.company_id,
            active=True
        )
        .order_by("-capacity")
        .first()
    )


def select_best_trailer(load):
    return (
        Trailer.objects.filter(
            account=load.account,
            company_id=load.company_id,
            available=True
        )
        .order_by("-capacity")
        .first()
    )
