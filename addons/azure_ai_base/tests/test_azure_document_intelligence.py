import base64
from unittest.mock import patch

from odoo.addons.azure_ai_base.models import azure_document_intelligence as di_module
from odoo.tests.common import TransactionCase, tagged


class _Response:
    def __init__(self, json_data=None, status_code=200, headers=None):
        self._json = json_data or {}
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


ANALYZE_RESULT = {
    "apiVersion": "2024-11-30",
    "modelId": "prebuilt-invoice",
    "documents": [
        {
            "docType": "invoice",
            "confidence": 0.94,
            "fields": {
                "VendorName": {
                    "type": "string",
                    "valueString": "Contoso Ltd",
                    "content": "Contoso Ltd",
                    "confidence": 0.97,
                },
                "InvoiceDate": {
                    "type": "date",
                    "valueDate": "2026-03-04",
                    "confidence": 0.91,
                },
                "InvoiceTotal": {
                    "type": "currency",
                    "valueCurrency": {"amount": 119.0, "currencyCode": "EUR"},
                    "confidence": 0.88,
                },
                "Quantity": {"type": "number", "valueNumber": 3, "confidence": 0.8},
                "PaymentDetails": {
                    "type": "array",
                    "valueArray": [
                        {
                            "type": "object",
                            "valueObject": {
                                "IBAN": {
                                    "type": "string",
                                    "valueString": "DE02120300000000202051",
                                }
                            },
                        }
                    ],
                },
                "VendorAddress": {
                    "type": "address",
                    "valueAddress": {"city": "Berlin", "postalCode": "10115"},
                },
                "Mystery": {"type": "unheardOf", "content": "raw text"},
            },
        }
    ],
}


@tagged("post_install", "-at_install")
class TestAzureDocumentIntelligence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.di = cls.env["azure.document.intelligence"]

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("azure_ai.di_endpoint", "https://foundry.example.com/")
        params.set_param("azure_ai.di_timeout", "30")
        # _analyze authenticates through ms.entra.auth; stub it so these tests
        # only exercise the Document Intelligence layer.
        patcher = patch.object(
            type(self.env["ms.entra.auth"]),
            "_auth_headers",
            return_value=(True, {"Authorization": "Bearer token"}),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        sleep_patcher = patch.object(di_module.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    # ------------------------------------------------------------------
    # Analyze
    # ------------------------------------------------------------------

    def test_analyze_submits_base64_and_returns_result(self):
        submit = _Response(
            status_code=202,
            headers={"Operation-Location": "https://foundry.example.com/op/1"},
        )
        poll = _Response({"status": "succeeded", "analyzeResult": ANALYZE_RESULT})
        with (
            patch.object(di_module.requests, "post", return_value=submit) as post,
            patch.object(di_module.requests, "get", return_value=poll),
        ):
            ok, result = self.di._analyze("prebuilt-invoice", b"%PDF-1.7 fake")

        self.assertTrue(ok)
        self.assertEqual(result["modelId"], "prebuilt-invoice")
        self.assertEqual(
            post.call_args.args[0],
            "https://foundry.example.com/documentintelligence"
            "/documentModels/prebuilt-invoice:analyze",
        )
        self.assertEqual(
            post.call_args.kwargs["params"], {"api-version": di_module.DEFAULT_API_VERSION}
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"base64Source": base64.b64encode(b"%PDF-1.7 fake").decode()},
        )

    def test_analyze_polls_until_terminal_state(self):
        submit = _Response(
            status_code=202,
            headers={"Operation-Location": "https://foundry.example.com/op/1"},
        )
        polls = [
            _Response({"status": "notStarted"}),
            _Response({"status": "running"}),
            _Response({"status": "succeeded", "analyzeResult": ANALYZE_RESULT}),
        ]
        with (
            patch.object(di_module.requests, "post", return_value=submit),
            patch.object(di_module.requests, "get", side_effect=polls) as get,
        ):
            ok, result = self.di._analyze("prebuilt-invoice", b"x")
        self.assertTrue(ok)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(result["modelId"], "prebuilt-invoice")

    def test_analyze_reports_failed_operation(self):
        submit = _Response(
            status_code=202,
            headers={"Operation-Location": "https://foundry.example.com/op/1"},
        )
        poll = _Response(
            {"status": "failed", "error": {"code": "InvalidRequest", "message": "bad pdf"}}
        )
        with (
            patch.object(di_module.requests, "post", return_value=submit),
            patch.object(di_module.requests, "get", return_value=poll),
        ):
            ok, error = self.di._analyze("prebuilt-invoice", b"x")
        self.assertFalse(ok)
        self.assertEqual(error, "bad pdf")

    def test_analyze_gives_up_after_the_timeout(self):
        self.env["ir.config_parameter"].sudo().set_param("azure_ai.di_timeout", "0")
        submit = _Response(
            status_code=202,
            headers={"Operation-Location": "https://foundry.example.com/op/1"},
        )
        with (
            patch.object(di_module.requests, "post", return_value=submit),
            patch.object(
                di_module.requests, "get", return_value=_Response({"status": "running"})
            ),
        ):
            ok, error = self.di._analyze("prebuilt-invoice", b"x")
        self.assertFalse(ok)
        self.assertIn("did not finish", error)

    def test_analyze_without_endpoint_fails_before_any_request(self):
        self.env["ir.config_parameter"].sudo().set_param("azure_ai.di_endpoint", "")
        with patch.object(di_module.requests, "post") as post:
            ok, error = self.di._analyze("prebuilt-invoice", b"x")
        self.assertFalse(ok)
        self.assertIn("endpoint not configured", error)
        post.assert_not_called()

    def test_analyze_without_operation_location_fails(self):
        with patch.object(
            di_module.requests, "post", return_value=_Response(status_code=202)
        ):
            ok, error = self.di._analyze("prebuilt-invoice", b"x")
        self.assertFalse(ok)
        self.assertIn("Operation-Location", error)

    # ------------------------------------------------------------------
    # Response decoding
    # ------------------------------------------------------------------

    def test_document_fields_decode_every_value_type(self):
        fields = self.di._document_fields(ANALYZE_RESULT)
        self.assertEqual(fields["VendorName"]["value"], "Contoso Ltd")
        self.assertEqual(fields["VendorName"]["confidence"], 0.97)
        self.assertEqual(fields["InvoiceDate"]["value"], "2026-03-04")
        self.assertEqual(
            fields["InvoiceTotal"]["value"], {"amount": 119.0, "currencyCode": "EUR"}
        )
        self.assertEqual(fields["Quantity"]["value"], 3)
        self.assertEqual(
            fields["PaymentDetails"]["value"],
            [{"IBAN": "DE02120300000000202051"}],
        )
        self.assertEqual(
            fields["VendorAddress"]["value"], {"city": "Berlin", "postalCode": "10115"}
        )

    def test_unknown_field_type_falls_back_to_content(self):
        self.assertEqual(
            self.di._document_fields(ANALYZE_RESULT)["Mystery"]["value"], "raw text"
        )

    def test_document_confidence(self):
        self.assertEqual(self.di._document_confidence(ANALYZE_RESULT), 0.94)

    def test_no_recognised_document_yields_empty_fields(self):
        self.assertEqual(self.di._document_fields({"documents": []}), {})
        self.assertIsNone(self.di._document_confidence({}))

    def test_the_content_type_does_not_clobber_the_auth_header(self):
        submit = _Response(
            status_code=202,
            headers={"Operation-Location": "https://foundry.example.com/op/1"},
        )
        poll = _Response({"status": "succeeded", "analyzeResult": ANALYZE_RESULT})
        with (
            patch.object(di_module.requests, "post", return_value=submit) as post,
            patch.object(di_module.requests, "get", return_value=poll),
        ):
            self.di._analyze("prebuilt-invoice", b"x")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer token")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_a_failed_token_stops_the_analysis(self):
        with (
            patch.object(
                type(self.env["ms.entra.auth"]),
                "_auth_headers",
                return_value=(False, "Unknown ms_graph.auth_mode 'nope'"),
            ),
            patch.object(di_module.requests, "post") as post,
        ):
            ok, error = self.di._analyze("prebuilt-invoice", b"x")
        self.assertFalse(ok)
        self.assertIn("auth_mode", error)
        post.assert_not_called()
