import base64
import contextlib
import logging
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from odoo import models

_logger = logging.getLogger(__name__)

DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
IMDS_URL = "http://169.254.169.254/metadata/identity/oauth2/token"
IMDS_API_VERSION = "2018-02-01"
IDENTITY_API_VERSION = "2019-08-01"
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
ASSERTION_TTL = 600  # Entra rejects a client assertion valid for longer
ASSERTION_SKEW = 60  # backdate nbf to absorb host clock drift
EXPIRY_SKEW = 120  # refresh this many seconds before the token expires
DEFAULT_TTL = 3600
TOKEN_TIMEOUT = 15
# Short connect timeout: off Azure, 169.254.169.254 is unroutable and must fail
# fast; on Azure the endpoint itself can be slow to answer.
IMDS_TIMEOUT = (3, 15)

MODES = ("client_secret", "certificate", "managed_identity", "workload_identity")

# Tokens are cached per Odoo worker, keyed by the identity and scope they were
# issued for. Each worker authenticates once per scope and reuses the token
# until it is within EXPIRY_SKEW of expiry.
_token_cache = {}
_token_lock = threading.Lock()


def _as_scope(value):
    """Graph-style scope: https://graph.microsoft.com/.default"""
    value = value.strip()
    return value if value.endswith("/.default") else f"{value.rstrip('/')}/.default"


def _as_resource(value):
    """Managed-identity style resource: https://graph.microsoft.com"""
    value = value.strip()
    return value.removesuffix("/.default")


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _error_message(exc):
    """Microsoft's error_description when the body is parseable, else str(exc)."""
    msg = str(exc)
    with contextlib.suppress(Exception):
        body = exc.response.json()
        error = body.get("error")
        msg = (
            body.get("error_description")
            or body.get("Message")
            or (error if isinstance(error, str) else None)
            or msg
        )
    # str(): the caller must never see this raise, whatever the body held.
    return str(msg).strip()


def _expires_at(body, now):
    """Absolute expiry, from expires_in (relative) or expires_on (epoch).

    IMDS returns both, as strings; the Entra token endpoint returns expires_in
    as an integer. A token with neither is treated as one hour.
    """
    ttl = None
    with contextlib.suppress(TypeError, ValueError):
        ttl = int(body.get("expires_in"))
    if ttl is None:
        with contextlib.suppress(TypeError, ValueError):
            ttl = int(body.get("expires_on")) - int(now.timestamp())
    if ttl is None:
        ttl = DEFAULT_TTL
    # Never past the token's own lifetime: a token shorter than the skew is
    # simply not cached.
    return now + timedelta(seconds=max(0, ttl - EXPIRY_SKEW))


class MsEntraAuth(models.AbstractModel):
    """Microsoft Entra ID tokens for any Azure resource.

    `_get_token(scope)` returns an application token acquired with the
    configured credential: a client secret, a certificate, the platform's
    managed identity, or a federated workload identity (AKS). Callers pass the
    scope of the API they are calling, so one identity serves Graph, ARM, Key
    Vault and custom APIs alike.
    """

    _name = "ms.entra.auth"
    _description = "Microsoft Entra ID token service"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _get_param(self, key, default=""):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default)
        return (value or "").strip()

    def _get_credentials(self):
        """Return (True, credentials) or (False, error_message).

        `client_id` carries whichever identity the mode selects: the app
        registration for client_secret and certificate, the user-assigned
        managed identity (empty for system-assigned) for managed_identity, the
        federated identity for workload_identity.
        """
        mode = self._get_param("ms_graph.auth_mode") or "client_secret"
        if mode not in MODES:
            return False, f"Unknown ms_graph.auth_mode '{mode}'"

        authority = self._get_param("ms_graph.authority")
        creds = {
            "mode": mode,
            "authority": authority or DEFAULT_AUTHORITY,
            "tenant_id": self._get_param("ms_graph.tenant_id"),
            "client_id": self._get_param("ms_graph.client_id"),
            "client_secret": self._get_param("ms_graph.client_secret"),
            "certificate": self._get_param("ms_graph.certificate"),
            "certificate_path": self._get_param("ms_graph.certificate_path"),
            "certificate_password": self._get_param("ms_graph.certificate_password"),
            "federated_token_file": self._get_param("ms_graph.federated_token_file"),
        }

        if mode == "managed_identity":
            # Tenant and credential live on the platform; only the optional
            # user-assigned identity is configured here.
            creds["client_id"] = self._get_param("ms_graph.managed_identity_client_id")
            return True, creds

        if mode == "workload_identity":
            # The AKS workload-identity webhook injects this environment into
            # the pod; a config parameter overrides whatever it set.
            creds["tenant_id"] = creds["tenant_id"] or os.environ.get(
                "AZURE_TENANT_ID", ""
            )
            creds["client_id"] = creds["client_id"] or os.environ.get(
                "AZURE_CLIENT_ID", ""
            )
            creds["federated_token_file"] = creds[
                "federated_token_file"
            ] or os.environ.get("AZURE_FEDERATED_TOKEN_FILE", "")
            creds["authority"] = (
                authority or os.environ.get("AZURE_AUTHORITY_HOST") or DEFAULT_AUTHORITY
            )

        missing = []
        if not creds["tenant_id"]:
            missing.append("ms_graph.tenant_id")
        if not creds["client_id"]:
            missing.append("ms_graph.client_id")
        if mode == "client_secret" and not creds["client_secret"]:
            missing.append("ms_graph.client_secret")
        if mode == "certificate" and not (
            creds["certificate"] or creds["certificate_path"]
        ):
            missing.append("ms_graph.certificate")
        if mode == "workload_identity" and not creds["federated_token_file"]:
            missing.append("AZURE_FEDERATED_TOKEN_FILE")
        if missing:
            return False, f"Entra credentials not configured: {', '.join(missing)}"
        return True, creds

    def _cache_key(self, creds, scope):
        return (
            creds["mode"],
            creds["authority"],
            creds["tenant_id"],
            creds["client_id"],
            _as_scope(scope),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _get_token(self, scope):
        """Return (True, access_token) for `scope`, or (False, error_message).

        `scope` accepts either form — "https://graph.microsoft.com/.default" or
        the bare resource "https://graph.microsoft.com" — in every mode.
        """
        ok, creds = self._get_credentials()
        if not ok:
            return False, creds

        key = self._cache_key(creds, scope)
        entry = _token_cache.get(key)
        if entry and entry["expires_at"] > datetime.now(UTC):
            return True, entry["access_token"]

        # One acquisition at a time per worker: without the lock a burst of
        # requests would each hit the token endpoint and risk throttling.
        with _token_lock:
            entry = _token_cache.get(key)
            if entry and entry["expires_at"] > datetime.now(UTC):
                return True, entry["access_token"]
            return self._acquire_token(creds, scope, key)

    def _auth_headers(self, scope):
        """Return (True, {"Authorization": ...}) or (False, error_message)."""
        ok, token = self._get_token(scope)
        if not ok:
            return False, token
        return True, {"Authorization": f"Bearer {token}"}

    def _invalidate_token(self, scope=None):
        """Drop cached tokens for this worker: one scope, or all when None."""
        with _token_lock:
            if scope is None:
                _token_cache.clear()
                return
            wanted = _as_scope(scope)
            for key in [k for k in _token_cache if k[-1] == wanted]:
                del _token_cache[key]

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------
    def _acquire_token(self, creds, scope, key):
        now = datetime.now(UTC)
        try:
            if creds["mode"] == "managed_identity":
                resp = self._request_managed_identity(creds, scope)
            else:
                ok, data = self._client_credentials_form(creds, scope)
                if not ok:
                    return self._token_failed(creds, scope, key, data)
                resp = requests.post(
                    self._token_url(creds), data=data, timeout=TOKEN_TIMEOUT
                )
            resp.raise_for_status()
            body = resp.json()
            token = body["access_token"]
        except requests.HTTPError as e:
            return self._token_failed(creds, scope, key, _error_message(e))
        except Exception as e:
            return self._token_failed(creds, scope, key, str(e))

        expires_at = _expires_at(body, now)
        _token_cache[key] = {"access_token": token, "expires_at": expires_at}
        _logger.info(
            "ms_entra_token_acquired",
            extra={
                "event": "ms_entra_token_acquired",
                "mode": creds["mode"],
                "tenant_id": creds["tenant_id"],
                "client_id": creds["client_id"],
                "scope": _as_scope(scope),
                "expires_in_s": int((expires_at - now).total_seconds()),
            },
        )
        return True, token

    def _token_failed(self, creds, scope, key, message):
        _token_cache.pop(key, None)
        _logger.warning(
            "ms_entra_token_failed",
            extra={
                "event": "ms_entra_token_failed",
                "mode": creds["mode"],
                "tenant_id": creds["tenant_id"],
                "client_id": creds["client_id"],
                "scope": _as_scope(scope),
                "error": message,
            },
        )
        return False, message

    def _token_url(self, creds):
        authority = creds["authority"].rstrip("/")
        return f"{authority}/{creds['tenant_id']}/oauth2/v2.0/token"

    def _client_credentials_form(self, creds, scope):
        """Return (True, post_data) for the secret or certificate flow."""
        data = {
            "grant_type": "client_credentials",
            "scope": _as_scope(scope),
            "client_id": creds["client_id"],
        }
        if creds["mode"] == "client_secret":
            data["client_secret"] = creds["client_secret"]
            return True, data
        if creds["mode"] == "workload_identity":
            ok, assertion = self._read_federated_token(creds)
        else:
            ok, assertion = self._build_client_assertion(creds)
        if not ok:
            return False, assertion
        data["client_assertion_type"] = ASSERTION_TYPE
        data["client_assertion"] = assertion
        return True, data

    def _read_federated_token(self, creds):
        """Return (True, assertion) from the projected service account token.

        Kubernetes rotates the file well inside its lifetime, so it is read on
        every acquisition and the assertion itself is never cached.
        """
        path = creds["federated_token_file"]
        try:
            with open(path, encoding="ascii") as fh:
                assertion = fh.read().strip()
        except Exception as e:
            return False, f"Cannot read federated token: {e}"
        if not assertion:
            return False, f"Federated token file '{path}' is empty"
        return True, assertion

    def _request_managed_identity(self, creds, scope):
        """Token from the platform identity endpoint.

        App Service, Functions and Container Apps inject IDENTITY_ENDPOINT and
        IDENTITY_HEADER; everywhere else (VM, VMSS, AKS node identity) the
        token comes from IMDS.
        """
        params = {"resource": _as_resource(scope)}
        endpoint = os.environ.get("IDENTITY_ENDPOINT")
        secret = os.environ.get("IDENTITY_HEADER")
        if endpoint and secret:
            url = endpoint
            headers = {"X-IDENTITY-HEADER": secret}
            params["api-version"] = IDENTITY_API_VERSION
        else:
            url = IMDS_URL
            headers = {"Metadata": "true"}
            params["api-version"] = IMDS_API_VERSION
        if creds["client_id"]:
            params["client_id"] = creds["client_id"]
        return requests.get(url, headers=headers, params=params, timeout=IMDS_TIMEOUT)

    # ------------------------------------------------------------------
    # Certificate credential
    # ------------------------------------------------------------------
    def _load_certificate(self, creds):
        """Return (True, (private_key, certificate)) or (False, error_message).

        Accepts a PEM bundle holding both key and certificate, or a PKCS#12
        (.pfx) blob — from a file when ms_graph.certificate_path is set,
        otherwise from ms_graph.certificate, raw PEM or base64-encoded.
        """
        try:
            if creds["certificate_path"]:
                with open(creds["certificate_path"], "rb") as fh:
                    blob = fh.read()
            elif "-----BEGIN" in creds["certificate"]:
                blob = creds["certificate"].encode()
            else:
                blob = base64.b64decode(creds["certificate"], validate=True)
        except Exception as e:
            return False, f"Cannot read Entra certificate: {e}"

        password = creds["certificate_password"] or None
        try:
            if b"-----BEGIN" in blob:
                key = serialization.load_pem_private_key(
                    blob, password=password and password.encode()
                )
                cert = x509.load_pem_x509_certificate(blob)
            else:
                key, cert, _chain = pkcs12.load_key_and_certificates(
                    blob, password and password.encode()
                )
        except Exception as e:
            return False, f"Cannot load Entra certificate: {e}"
        if key is None or cert is None:
            return False, "Entra certificate must contain both key and certificate"
        if not isinstance(key, rsa.RSAPrivateKey):
            return False, "Entra certificate credentials require an RSA private key"
        return True, (key, cert)

    def _build_client_assertion(self, creds):
        """Return (True, signed_jwt) proving possession of the certificate."""
        ok, material = self._load_certificate(creds)
        if not ok:
            return False, material
        key, cert = material

        now = int(time.time())
        payload = {
            "aud": self._token_url(creds),
            "iss": creds["client_id"],
            "sub": creds["client_id"],
            "jti": str(uuid.uuid4()),
            "iat": now,
            "nbf": now - ASSERTION_SKEW,
            "exp": now + ASSERTION_TTL,
        }
        # x5t is defined as the certificate's SHA-1 thumbprint: the identifier
        # Entra matches against the registered key, not a signature.
        headers = {"x5t": _b64u(cert.fingerprint(hashes.SHA1())).decode()}
        return True, jwt.encode(payload, key, algorithm="RS256", headers=headers)
