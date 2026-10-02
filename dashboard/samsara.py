"""Server-side OAuth helpers for customer-specific Samsara connections."""

import base64
import hashlib
import json
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone


SAMSARA_API_BASE = "https://api.samsara.com"


class SamsaraError(Exception):
    """A safe-to-display error returned while connecting to Samsara."""


def oauth_is_configured():
    return bool(
        settings.SAMSARA_CLIENT_ID
        and settings.SAMSARA_CLIENT_SECRET
        and settings.SAMSARA_REDIRECT_URI
        and settings.SAMSARA_TOKEN_ENCRYPTION_KEY
    )


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise SamsaraError("The secure encryption package is not installed on the server.") from exc
    key = settings.SAMSARA_TOKEN_ENCRYPTION_KEY
    if not key:
        raise SamsaraError("Samsara token encryption is not configured.")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
    return Fernet(derived_key)


def encrypt_token(value):
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_token(value):
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SamsaraError("Saved Samsara credentials could not be decrypted.") from exc


def authorization_url(state):
    params = {
        "client_id": settings.SAMSARA_CLIENT_ID,
        "response_type": "code",
        "state": state,
        "redirect_uri": settings.SAMSARA_REDIRECT_URI,
    }
    return f"{SAMSARA_API_BASE}/oauth2/authorize?{urlencode(params)}"


def _token_request(values):
    credentials = f"{settings.SAMSARA_CLIENT_ID}:{settings.SAMSARA_CLIENT_SECRET}"
    basic = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    body = urlencode(values).encode("utf-8")
    request = Request(
        f"{SAMSARA_API_BASE}/oauth2/token",
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Avoid including provider response text, which could contain credentials.
        raise SamsaraError("Samsara did not accept the authorization. Check the app setup and try again.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SamsaraError("G-Fleet-IQ could not reach Samsara. Please try again.") from exc

    if not payload.get("access_token") or not payload.get("refresh_token"):
        raise SamsaraError("Samsara returned an incomplete authorization response.")
    return payload


def exchange_code(code):
    values = {"grant_type": "authorization_code", "code": code}
    if settings.SAMSARA_REDIRECT_URI:
        values["redirect_uri"] = settings.SAMSARA_REDIRECT_URI
    return _token_request(values)


def refresh_tokens(refresh_token):
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


def token_expiry(token_data):
    try:
        seconds = max(1, int(token_data.get("expires_in", 3600)))
    except (TypeError, ValueError):
        seconds = 3600
    return timezone.now() + timedelta(seconds=seconds)


def samsara_get(access_token, path):
    request = Request(
        f"{SAMSARA_API_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SamsaraError("Samsara authorization succeeded, but G-Fleet-IQ could not read account details.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SamsaraError("G-Fleet-IQ could not reach Samsara. Please try again.") from exc
