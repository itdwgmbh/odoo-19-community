import contextlib
import logging
from datetime import UTC, datetime, timedelta

import requests
from odoo import models

_logger = logging.getLogger(__name__)

# Module-level token cache survives across AbstractModel instantiations within
# a single Odoo worker. Each worker caches independently; tokens last ~60 min
# and we refresh 2 min before expiry.
_token_cache = {
    "access_token": None,
    "token_type": None,
    "expires_at": datetime.min.replace(tzinfo=UTC),
}

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


class MsGraphService(models.AbstractModel):
    _name = "ms.graph.service"
    _description = "Microsoft Graph low-level client"

    def _get_param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _get_credentials(self):
        tenant = self._get_param("ms_graph.tenant_id")
        client_id = self._get_param("ms_graph.client_id")
        client_secret = self._get_param("ms_graph.client_secret")
        if not all([tenant, client_id, client_secret]):
            return None
        return {
            "tenant_id": tenant,
            "client_id": client_id,
            "client_secret": client_secret,
        }

    def _ensure_token(self, creds):
        now = datetime.now(UTC)
        if _token_cache["access_token"] and _token_cache["expires_at"] > now:
            return True

        url = TOKEN_URL.format(tenant=creds["tenant_id"])
        data = {
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        }
        try:
            resp = requests.post(url, data=data, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            _token_cache["access_token"] = body["access_token"]
            _token_cache["token_type"] = body.get("token_type", "Bearer")
            _token_cache["expires_at"] = now + timedelta(minutes=58)
            _logger.info(
                "ms_graph_token_acquired",
                extra={
                    "event": "ms_graph_token_acquired",
                    "tenant_id": creds["tenant_id"],
                    "expires_in_s": int(
                        (_token_cache["expires_at"] - now).total_seconds()
                    ),
                },
            )
            return True
        except Exception as e:
            _logger.exception(
                "ms_graph_token_failed",
                extra={
                    "event": "ms_graph_token_failed",
                    "tenant_id": creds["tenant_id"],
                    "error": str(e),
                },
            )
            _token_cache["access_token"] = None
            return False

    def _graph_request(self, method, path, json_data=None, raw=False):
        """Low-level Graph request. Returns (success, response_or_error_message).

        - `path` is appended to GRAPH_BASE; pass a full URL only when paging
          via @odata.nextLink (caller's job to strip GRAPH_BASE if reusing).
        - On 204, returns (True, {}) — or (True, b"") when raw=True.
        - When `raw=True`, returns (True, response_bytes) on success instead
          of decoding JSON — used by callers that need RFC822 / binary
          payloads (e.g. /messages/{id}/$value).
        - On HTTP error, returns (False, server's error.message when parseable,
          else the raw exception string).
        """
        creds = self._get_credentials()
        if not creds:
            return False, "MS Graph credentials not configured"

        if not self._ensure_token(creds):
            return False, "Failed to acquire MS Graph token"

        url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
        headers = {
            "Authorization": f"{_token_cache['token_type']} {_token_cache['access_token']}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.request(
                method, url, headers=headers, json=json_data, timeout=30
            )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return True, (b"" if raw else {})
            if raw:
                return True, resp.content
            return True, resp.json()
        except requests.HTTPError as e:
            msg = str(e)
            with contextlib.suppress(Exception):
                msg = e.response.json().get("error", {}).get("message", msg)
            _logger.warning(
                "ms_graph_request_failed",
                extra={
                    "event": "ms_graph_request_failed",
                    "method": method,
                    "path": path,
                    "status": getattr(e.response, "status_code", None),
                    "error": msg,
                },
            )
            return False, msg
        except Exception as e:
            _logger.warning(
                "ms_graph_request_failed",
                extra={
                    "event": "ms_graph_request_failed",
                    "method": method,
                    "path": path,
                    "error": str(e),
                },
            )
            return False, str(e)
