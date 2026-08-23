import contextlib
import logging

import requests
from odoo import models

_logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class MsGraphService(models.AbstractModel):
    _name = "ms.graph.service"
    _description = "Microsoft Graph low-level client"

    def _graph_request(self, method, path, json_data=None, raw=False):
        """Low-level Graph request. Returns (success, response_or_error_message).

        - Authenticates through `ms.entra.auth`, which owns the credential and
          the per-worker token cache.
        - `path` is appended to GRAPH_BASE; pass a full URL only when paging
          via @odata.nextLink (caller's job to strip GRAPH_BASE if reusing).
        - On 204, returns (True, {}) — or (True, b"") when raw=True.
        - When `raw=True`, returns (True, response_bytes) on success instead
          of decoding JSON — used by callers that need RFC822 / binary
          payloads (e.g. /messages/{id}/$value).
        - On HTTP error, returns (False, server's error.message when parseable,
          else the raw exception string).
        """
        ok, headers = self.env["ms.entra.auth"]._auth_headers(GRAPH_SCOPE)
        if not ok:
            return False, headers

        url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
        headers["Content-Type"] = "application/json"
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
