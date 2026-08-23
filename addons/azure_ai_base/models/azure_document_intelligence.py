import base64
import contextlib
import logging
import time

import requests
from odoo import models

_logger = logging.getLogger(__name__)

# Resource scope for every Azure AI Services / Foundry data-plane call.
DI_SCOPE = "https://cognitiveservices.azure.com/.default"
# v4.0 GA. Overridable via ir.config_parameter for a later GA release.
DEFAULT_API_VERSION = "2024-11-30"
# Analysis is a long-running operation: POST returns 202 and we poll the URL
# from Operation-Location until it leaves the running states.
_TERMINAL_STATES = ("succeeded", "failed", "canceled")
_POLL_INTERVAL_S = 2
_DEFAULT_TIMEOUT_S = 120


class AzureDocumentIntelligence(models.AbstractModel):
    """Azure AI Document Intelligence data-plane client.

    Wraps the analyze long-running operation and the field encoding of the
    response, so callers deal in plain Python values and never in
    ``valueCurrency`` / ``valueArray`` shapes. It knows nothing about what the
    fields mean — mapping ``VendorName`` to a business field is the caller's
    job.

    Authenticates through `ms.entra.auth`, so it inherits every credential mode
    that service supports. The identity needs the **Cognitive Services User**
    role on the Foundry resource.
    """

    _name = "azure.document.intelligence"
    _description = "Azure AI Document Intelligence client"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _get_param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _endpoint(self):
        return (self._get_param("azure_ai.di_endpoint") or "").rstrip("/")

    def _api_version(self):
        return self._get_param("azure_ai.di_api_version") or DEFAULT_API_VERSION

    def _timeout(self):
        try:
            return int(self._get_param("azure_ai.di_timeout") or _DEFAULT_TIMEOUT_S)
        except ValueError:
            return _DEFAULT_TIMEOUT_S

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def _error_message(self, exc):
        """Document Intelligence's error.message when parseable, else str(exc)."""
        msg = str(exc)
        with contextlib.suppress(Exception):
            msg = exc.response.json().get("error", {}).get("message", msg)
        return msg

    def _analyze(self, model_id, content, locale=None, pages=None):
        """Run a Document Intelligence model over `content` (raw bytes).

        Submits the document, polls the operation until it reaches a terminal
        state, and returns (True, analyzeResult) or (False, error_message).
        `analyzeResult` is the service's own object: `content`, `pages`,
        `tables`, `documents`, ... Read fields out of it with
        `_document_fields`.
        """
        endpoint = self._endpoint()
        if not endpoint:
            return False, "Azure Document Intelligence endpoint not configured"

        ok, headers = self.env["ms.entra.auth"]._auth_headers(DI_SCOPE)
        if not ok:
            return False, headers
        headers = {**headers, "Content-Type": "application/json"}

        params = {"api-version": self._api_version()}
        if locale:
            params["locale"] = locale
        if pages:
            params["pages"] = pages
        url = f"{endpoint}/documentintelligence/documentModels/{model_id}:analyze"
        payload = {"base64Source": base64.b64encode(content).decode()}

        try:
            resp = requests.post(
                url, headers=headers, params=params, json=payload, timeout=60
            )
            resp.raise_for_status()
            operation_url = resp.headers.get("Operation-Location")
        except requests.HTTPError as e:
            msg = self._error_message(e)
            _logger.warning(
                "azure_di_analyze_failed",
                extra={
                    "event": "azure_di_analyze_failed",
                    "model_id": model_id,
                    "status": getattr(e.response, "status_code", None),
                    "error": msg,
                },
            )
            return False, msg
        except Exception as e:
            _logger.warning(
                "azure_di_analyze_failed",
                extra={
                    "event": "azure_di_analyze_failed",
                    "model_id": model_id,
                    "error": str(e),
                },
            )
            return False, str(e)

        if not operation_url:
            return False, "Document Intelligence returned no Operation-Location"
        return self._poll(operation_url, model_id, resp.headers.get("Retry-After"))

    def _poll(self, operation_url, model_id, retry_after=None):
        """Poll an analyze operation until it terminates or the budget runs out."""
        # The token is fetched per poll so a long-running analysis cannot fail
        # on an expiry mid-loop; ms.entra.auth serves it from cache.
        deadline = time.monotonic() + self._timeout()
        delay = _POLL_INTERVAL_S
        with contextlib.suppress(TypeError, ValueError):
            delay = max(int(retry_after), _POLL_INTERVAL_S)

        while True:
            time.sleep(delay)
            ok, headers = self.env["ms.entra.auth"]._auth_headers(DI_SCOPE)
            if not ok:
                return False, headers
            try:
                resp = requests.get(operation_url, headers=headers, timeout=30)
                resp.raise_for_status()
                body = resp.json()
            except requests.HTTPError as e:
                return False, self._error_message(e)
            except Exception as e:
                return False, str(e)

            status = (body.get("status") or "").lower()
            if status == "succeeded":
                return True, body.get("analyzeResult") or {}
            if status in _TERMINAL_STATES:
                error = (body.get("error") or {}).get("message") or status
                _logger.warning(
                    "azure_di_analyze_failed",
                    extra={
                        "event": "azure_di_analyze_failed",
                        "model_id": model_id,
                        "status": status,
                        "error": error,
                    },
                )
                return False, error

            if time.monotonic() >= deadline:
                _logger.warning(
                    "azure_di_analyze_timeout",
                    extra={
                        "event": "azure_di_analyze_timeout",
                        "model_id": model_id,
                        "timeout_s": self._timeout(),
                    },
                )
                return False, (
                    f"Document Intelligence did not finish within {self._timeout()}s"
                )
            delay = _POLL_INTERVAL_S
            with contextlib.suppress(TypeError, ValueError):
                delay = max(int(resp.headers.get("Retry-After")), _POLL_INTERVAL_S)

    # ------------------------------------------------------------------
    # Response decoding
    # ------------------------------------------------------------------

    def _field_value(self, field):
        """Plain Python value for one DocumentField, whatever its type.

        Arrays become lists and objects become dicts, both decoded recursively.
        `currency` and `address` keep their service shape (`amount` /
        `currencyCode`, and the address components) because both halves carry
        meaning. Anything unrecognised falls back to the matched text.
        """
        if not isinstance(field, dict):
            return None
        field_type = field.get("type")
        if field_type == "array":
            return [self._field_value(item) for item in field.get("valueArray") or []]
        if field_type == "object":
            return {
                name: self._field_value(sub)
                for name, sub in (field.get("valueObject") or {}).items()
            }
        if field_type == "currency":
            return field.get("valueCurrency")
        if field_type == "address":
            return field.get("valueAddress")
        if field_type:
            key = f"value{field_type[0].upper()}{field_type[1:]}"
            if key in field:
                return field[key]
        return field.get("content")

    def _document_fields(self, analyze_result, index=0):
        """Fields of one analyzed document as {name: {value, confidence, content}}.

        Returns an empty dict when the model recognised no document, which is
        what a blank or unreadable page produces.
        """
        documents = (analyze_result or {}).get("documents") or []
        if index >= len(documents):
            return {}
        fields = documents[index].get("fields") or {}
        return {
            name: {
                "value": self._field_value(field),
                "confidence": field.get("confidence"),
                "content": field.get("content"),
            }
            for name, field in fields.items()
        }

    def _document_confidence(self, analyze_result, index=0):
        """Model confidence for the analyzed document, or None."""
        documents = (analyze_result or {}).get("documents") or []
        if index >= len(documents):
            return None
        return documents[index].get("confidence")
