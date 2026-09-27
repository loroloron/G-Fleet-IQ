from django.conf import settings
from django.http import HttpResponse


def service_worker(request):
    """Serve the PWA worker at the site root so it can cover the whole app."""
    script_path = settings.BASE_DIR / "core" / "static" / "pwa" / "service-worker.js"
    response = HttpResponse(
        script_path.read_text(encoding="utf-8"),
        content_type="application/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response
