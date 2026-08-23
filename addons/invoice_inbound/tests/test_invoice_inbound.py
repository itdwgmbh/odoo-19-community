import base64
import hashlib
from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common import (
    CII_CREDIT_NOTE_XML,
    CII_XML,
    DI_ANALYZE_RESULT,
    build_pdf,
    di_credit_note_result,
)


@tagged("post_install", "-at_install")
class TestInvoiceInbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Invoice = cls.env["invoice.inbound"]
        cls.einvoice_pdf = build_pdf([("factur-x.xml", CII_XML)])
        cls.scan_pdf = build_pdf()

    def _create(self, content=None, file_name="invoice.pdf", **values):
        return self.Invoice._create_from_file(
            content if content is not None else self.scan_pdf, file_name, values
        )

    def _patch_analyze(self, return_value):
        patcher = patch.object(
            type(self.env["azure.document.intelligence"]),
            "_analyze",
            return_value=return_value,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def test_create_stores_checksum_and_names_the_record_after_the_file(self):
        invoice = self._create(file_name="RE-2026-0042.pdf")
        self.assertEqual(invoice.name, "RE-2026-0042.pdf")
        self.assertEqual(
            invoice.file_checksum, hashlib.sha256(self.scan_pdf).hexdigest()
        )
        self.assertEqual(invoice.state, "incoming")

    def test_create_computes_the_checksum_when_only_a_file_is_given(self):
        invoice = self.Invoice.create(
            {"file": base64.b64encode(self.scan_pdf), "file_name": "x.pdf"}
        )
        self.assertEqual(
            invoice.file_checksum, hashlib.sha256(self.scan_pdf).hexdigest()
        )

    def test_a_file_without_a_name_still_gets_one(self):
        invoice = self.Invoice.create({"file": base64.b64encode(self.scan_pdf)})
        self.assertTrue(invoice.name)

    # ------------------------------------------------------------------
    # E-invoice extraction, which runs on create
    # ------------------------------------------------------------------

    def test_embedded_einvoice_is_read_on_create(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(invoice.extraction_state, "done")
        self.assertEqual(invoice.extraction_method, "einvoice")
        self.assertEqual(invoice.extraction_confidence, 1.0)
        self.assertEqual(invoice.invoice_number, "RE-2026-0042")
        self.assertEqual(invoice.invoice_date, date(2026, 3, 4))
        self.assertEqual(invoice.date_due, date(2026, 4, 3))
        self.assertEqual(invoice.partner_name, "Lieferant GmbH")
        self.assertEqual(invoice.partner_vat, "DE123456789")
        self.assertEqual(invoice.amount_total, 529.87)
        self.assertEqual(invoice.currency_id.name, "EUR")

    def test_a_plain_scan_stays_pending_for_the_ocr_cron(self):
        invoice = self._create(self.scan_pdf)
        self.assertEqual(invoice.extraction_state, "pending")
        self.assertFalse(invoice.extraction_method)

    def test_the_document_name_survives_extraction(self):
        invoice = self._create(self.einvoice_pdf, file_name="scan-4711.pdf")
        self.assertEqual(invoice.name, "scan-4711.pdf")

    def test_extraction_payload_is_keyed_on_this_models_fields(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(invoice.extraction_payload["invoice_number"]["value"],
                         "RE-2026-0042")
        self.assertEqual(invoice.extraction_payload["amount_total"]["confidence"], 1.0)

    def test_a_vendor_is_matched_on_vat(self):
        partner = self.env["res.partner"].create(
            {"name": "Something Else GmbH", "vat": "DE123456789"}
        )
        self.assertEqual(self._create(self.einvoice_pdf).partner_id, partner)

    def test_a_vendor_is_matched_on_name_when_the_vat_is_unknown(self):
        partner = self.env["res.partner"].create({"name": "Lieferant GmbH"})
        self.assertEqual(self._create(self.einvoice_pdf).partner_id, partner)

    def test_a_vendor_already_set_is_never_replaced(self):
        self.env["res.partner"].create({"name": "Lieferant GmbH"})
        chosen = self.env["res.partner"].create({"name": "Chosen By Hand"})
        invoice = self._create(self.einvoice_pdf, partner_id=chosen.id)
        self.assertEqual(invoice.partner_id, chosen)

    # ------------------------------------------------------------------
    # OCR extraction
    # ------------------------------------------------------------------

    def test_ocr_fills_the_header_fields(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        ok, _message = invoice._extract()
        self.assertTrue(ok)
        self.assertEqual(invoice.extraction_method, "ocr")
        self.assertEqual(invoice.extraction_state, "done")
        self.assertEqual(invoice.extraction_confidence, 0.93)
        self.assertEqual(invoice.partner_name, "Scan Supplies GmbH")
        self.assertEqual(invoice.partner_vat, "DE999888777")
        self.assertEqual(invoice.invoice_number, "SC-5501")
        self.assertEqual(invoice.invoice_date, date(2026, 2, 1))
        self.assertEqual(invoice.date_due, date(2026, 3, 3))
        self.assertEqual(invoice.purchase_order, "PO-7788")
        self.assertEqual(invoice.payment_terms, "Net 30")

    def test_ocr_unpacks_currency_amounts_and_the_currency_code(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.amount_untaxed, 200.0)
        self.assertEqual(invoice.amount_tax, 38.0)
        self.assertEqual(invoice.amount_total, 238.0)
        self.assertEqual(invoice.currency_id.name, "EUR")

    def test_ocr_reads_the_iban_out_of_the_payment_details_array(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.iban, "DE44500105175407324931")

    def test_ocr_records_per_field_confidence(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.extraction_payload["invoice_number"]["confidence"], 0.95)
        self.assertEqual(invoice.extraction_payload["amount_total"]["value"], 238.0)

    def test_a_failed_analysis_is_recorded_on_the_record(self):
        self._patch_analyze((False, "Document Intelligence endpoint not configured"))
        invoice = self._create(self.scan_pdf)
        ok, message = invoice._extract()
        self.assertFalse(ok)
        self.assertEqual(invoice.extraction_state, "failed")
        self.assertEqual(
            invoice.extraction_error, "Document Intelligence endpoint not configured"
        )
        self.assertEqual(message, "Document Intelligence endpoint not configured")

    def test_an_unrecognised_document_is_recorded_as_a_failure(self):
        self._patch_analyze((True, {"documents": []}))
        invoice = self._create(self.scan_pdf)
        ok, _message = invoice._extract()
        self.assertFalse(ok)
        self.assertEqual(invoice.extraction_state, "failed")

    def test_the_extract_button_reports_a_failure_to_the_user(self):
        self._patch_analyze((False, "boom"))
        invoice = self._create(self.scan_pdf)
        with self.assertRaises(UserError):
            invoice.action_extract()

    def test_extraction_leaves_hand_edited_fields_alone(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice.invoice_number = "TYPED BY HAND"
        invoice._extract()
        self.assertEqual(invoice.invoice_number, "TYPED BY HAND")
        self.assertEqual(invoice.partner_name, "Scan Supplies GmbH")

    def test_re_extracting_on_purpose_overwrites(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice.invoice_number = "TYPED BY HAND"
        invoice.action_extract()
        self.assertEqual(invoice.invoice_number, "SC-5501")

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def test_incoming_can_be_validated_then_paid(self):
        invoice = self._create()
        invoice.action_validate()
        self.assertEqual(invoice.state, "validated")
        invoice.action_mark_paid()
        self.assertEqual(invoice.state, "paid")
        self.assertEqual(invoice.payment_date, date.today())

    def test_incoming_cannot_be_paid_directly(self):
        invoice = self._create()
        with self.assertRaises(UserError):
            invoice.action_mark_paid()

    def test_a_paid_invoice_cannot_be_rejected(self):
        invoice = self._create()
        invoice.action_validate()
        invoice.action_mark_paid()
        with self.assertRaises(UserError):
            invoice.action_reject()

    def test_rejecting_and_validating_again(self):
        invoice = self._create()
        invoice.action_reject()
        self.assertEqual(invoice.state, "rejected")
        invoice.rejection_reason = "Wrong billing address"
        invoice.action_validate()
        self.assertEqual(invoice.state, "validated")
        self.assertFalse(invoice.rejection_reason)

    def test_reset_clears_the_payment_date(self):
        invoice = self._create()
        invoice.action_validate()
        invoice.action_mark_paid()
        invoice.action_reset_to_incoming()
        self.assertEqual(invoice.state, "incoming")
        self.assertFalse(invoice.payment_date)

    def test_a_blocked_transition_moves_no_record_in_the_batch(self):
        first = self._create()
        second = self._create(file_name="other.pdf")
        first.action_validate()
        with self.assertRaises(UserError):
            (first | second).action_mark_paid()
        self.assertEqual(first.state, "validated")
        self.assertEqual(second.state, "incoming")

    # ------------------------------------------------------------------
    # OCR cron
    # ------------------------------------------------------------------

    def test_the_ocr_cron_does_nothing_until_azure_is_configured(self):
        self.env["ir.config_parameter"].sudo().set_param("azure_ai.di_endpoint", "")
        invoice = self._create(self.scan_pdf)
        with patch.object(
            type(self.env["azure.document.intelligence"]), "_analyze"
        ) as analyze:
            self.Invoice._cron_extract()
        analyze.assert_not_called()
        self.assertEqual(invoice.extraction_state, "pending")

    # ------------------------------------------------------------------
    # Reading the file back
    # ------------------------------------------------------------------

    def test_the_file_is_read_as_bytes_even_with_bin_size_set(self):
        # The web client sets bin_size on form reads, which turns a Binary into
        # its human readable size. Extraction must not see that.
        invoice = self._create(self.einvoice_pdf).with_context(bin_size=True)
        self.assertEqual(invoice._content(), self.einvoice_pdf)
        invoice.invoice_number = False
        invoice.action_extract()
        self.assertEqual(invoice.invoice_number, "RE-2026-0042")

    # ------------------------------------------------------------------
    # Credit notes
    # ------------------------------------------------------------------

    def test_a_credit_note_pdf_is_recognised_as_one(self):
        invoice = self._create(build_pdf([("factur-x.xml", CII_CREDIT_NOTE_XML)]))
        self.assertEqual(invoice.document_type, "credit_note")

    def test_a_credit_note_keeps_positive_amounts_and_a_negative_signed_total(self):
        invoice = self._create(build_pdf([("factur-x.xml", CII_CREDIT_NOTE_XML)]))
        self.assertEqual(invoice.amount_total, 529.87)
        self.assertEqual(invoice.amount_total_signed, -529.87)

    def test_an_invoice_signs_its_total_positively(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(invoice.amount_total_signed, invoice.amount_total)

    def test_the_document_type_wins_over_the_default_without_overwrite(self):
        # document_type defaults to "invoice", which is truthy, so the
        # skip-non-empty rule must not keep the extractor out.
        invoice = self._create(build_pdf([("factur-x.xml", CII_CREDIT_NOTE_XML)]))
        self.assertEqual(invoice.document_type, "credit_note")

    def test_ocr_reads_a_credit_note_from_its_negative_total(self):
        self._patch_analyze((True, di_credit_note_result()))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.document_type, "credit_note")
        # Stored the way an e-invoice would state them.
        self.assertEqual(invoice.amount_total, 238.0)
        self.assertEqual(invoice.amount_untaxed, 200.0)
        self.assertEqual(invoice.amount_tax, 38.0)
        self.assertEqual(invoice.amount_total_signed, -238.0)

    def test_ocr_leaves_a_positive_total_as_an_invoice(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.document_type, "invoice")

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    def test_einvoice_lines_become_records(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(len(invoice.line_ids), 2)
        first = invoice.line_ids[0]
        self.assertEqual(first.name, "Trennblätter A4")
        self.assertEqual(first.product_code, "TB100A4")
        self.assertEqual(first.quantity, 20.0)
        self.assertEqual(first.uom, "H87")
        self.assertEqual(first.price_unit, 9.9)
        self.assertEqual(first.tax_rate, 19.0)
        self.assertEqual(first.amount, 198.0)
        self.assertEqual(invoice.line_ids[1].name, "Joghurt Banane")

    def test_lines_carry_the_invoice_currency_and_company(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(invoice.line_ids.currency_id, invoice.currency_id)
        self.assertEqual(invoice.line_ids[0].company_id, invoice.company_id)

    def test_lines_that_add_up_are_reported_as_matching(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(invoice.lines_amount, 473.0)
        self.assertTrue(invoice.lines_match)

    def test_lines_that_do_not_add_up_are_reported_as_mismatched(self):
        invoice = self._create(self.einvoice_pdf)
        invoice.line_ids[0].amount = 1.0
        self.assertFalse(invoice.lines_match)

    def test_an_invoice_without_lines_does_not_claim_a_match(self):
        self.assertFalse(self._create(self.scan_pdf).lines_match)

    def test_ocr_lines_become_records(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(len(invoice.line_ids), 2)
        first = invoice.line_ids[0]
        self.assertEqual(first.name, "Consulting Services")
        self.assertEqual(first.product_code, "A123")
        self.assertEqual(first.quantity, 2.0)
        self.assertEqual(first.uom, "hours")
        self.assertEqual(first.price_unit, 30.0)
        self.assertEqual(first.amount, 60.0)
        # The service reports the rate as text.
        self.assertEqual(first.tax_rate, 19.0)
        self.assertEqual(first.confidence, 0.82)

    def test_ocr_keeps_a_sparse_line(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.line_ids[1].name, "Travel")
        self.assertEqual(invoice.line_ids[1].amount, 140.0)
        self.assertFalse(invoice.line_ids[1].quantity)

    def test_lines_are_not_replaced_unless_extraction_is_asked_for_again(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.einvoice_pdf)
        self.assertEqual(len(invoice.line_ids), 2)
        invoice.line_ids[0].name = "Corrected by hand"
        invoice._extract()
        self.assertEqual(invoice.line_ids[0].name, "Corrected by hand")

    def test_re_extracting_replaces_the_lines_wholesale(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        invoice.line_ids.create(
            {"invoice_id": invoice.id, "name": "Stale", "amount": 1.0}
        )
        self.assertEqual(len(invoice.line_ids), 3)
        invoice.action_extract()
        self.assertEqual(len(invoice.line_ids), 2)
        self.assertNotIn("Stale", invoice.line_ids.mapped("name"))

    def test_deleting_an_invoice_takes_its_lines(self):
        invoice = self._create(self.einvoice_pdf)
        line_ids = invoice.line_ids.ids
        invoice.unlink()
        self.assertFalse(self.env["invoice.inbound.line"].browse(line_ids).exists())

    def test_lines_stay_out_of_the_extraction_payload(self):
        invoice = self._create(self.einvoice_pdf)
        self.assertNotIn("lines", invoice.extraction_payload)

    # ------------------------------------------------------------------
    # Unit of measure
    # ------------------------------------------------------------------

    def test_the_unece_code_is_stored_and_spelled_out(self):
        line = self._create(self.einvoice_pdf).line_ids[0]
        self.assertEqual(line.uom, "H87")
        self.assertEqual(line.uom_label, "piece")

    def test_an_hour_code_reads_as_an_hour(self):
        line = self._create(self.einvoice_pdf).line_ids[0]
        line.uom = "HUR"
        self.assertEqual(line.uom_label, "hour")

    def test_a_lowercase_code_still_resolves(self):
        line = self._create(self.einvoice_pdf).line_ids[0]
        line.uom = "hur"
        self.assertEqual(line.uom_label, "hour")

    def test_an_unlisted_code_is_shown_unchanged(self):
        line = self._create(self.einvoice_pdf).line_ids[0]
        line.uom = "ZZZ"
        self.assertEqual(line.uom_label, "ZZZ")

    def test_free_text_from_ocr_is_shown_unchanged(self):
        self._patch_analyze((True, DI_ANALYZE_RESULT))
        invoice = self._create(self.scan_pdf)
        invoice._extract()
        self.assertEqual(invoice.line_ids[0].uom, "hours")
        self.assertEqual(invoice.line_ids[0].uom_label, "hours")

    def test_a_line_without_a_unit_has_no_label(self):
        line = self._create(self.einvoice_pdf).line_ids[0]
        line.uom = False
        self.assertFalse(line.uom_label)
