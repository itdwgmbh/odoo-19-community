from datetime import date

from odoo.tests.common import TransactionCase, tagged

from .common import (
    CII_CREDIT_NOTE_XML,
    CII_XML,
    UBL_CREDIT_NOTE_XML,
    UBL_TYPECODE_CREDIT_NOTE_XML,
    UBL_XML,
    build_pdf,
)


@tagged("post_install", "-at_install")
class TestEinvoiceParser(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parser = cls.env["invoice.einvoice.parser"]

    # ------------------------------------------------------------------
    # CII (ZUGFeRD 2.x / Factur-X / XRechnung CII)
    # ------------------------------------------------------------------

    def test_cii_header_fields(self):
        values = self.parser._parse(CII_XML)
        self.assertEqual(values["invoice_number"], "RE-2026-0042")
        self.assertEqual(values["invoice_date"], date(2026, 3, 4))
        self.assertEqual(values["date_due"], date(2026, 4, 3))
        self.assertEqual(values["partner_name"], "Lieferant GmbH")
        self.assertEqual(values["currency_code"], "EUR")
        self.assertEqual(values["payment_reference"], "RE-2026-0042")
        self.assertEqual(values["iban"], "DE02120300000000202051")
        self.assertEqual(values["purchase_order"], "PO-9182")
        self.assertEqual(values["payment_terms"], "Zahlbar innerhalb 30 Tagen netto")

    def test_cii_amounts(self):
        values = self.parser._parse(CII_XML)
        self.assertEqual(values["amount_untaxed"], 473.0)
        self.assertEqual(values["amount_tax"], 56.87)
        self.assertEqual(values["amount_total"], 529.87)

    def test_cii_prefers_the_vat_registration_over_the_tax_number(self):
        # The seller reports the Steuernummer (schemeID FC) first.
        self.assertEqual(self.parser._parse(CII_XML)["partner_vat"], "DE123456789")

    # ------------------------------------------------------------------
    # UBL (XRechnung UBL / Peppol BIS Billing 3.0)
    # ------------------------------------------------------------------

    def test_ubl_header_fields(self):
        values = self.parser._parse(UBL_XML)
        self.assertEqual(values["invoice_number"], "XR-2026-7")
        self.assertEqual(values["invoice_date"], date(2026, 3, 5))
        self.assertEqual(values["date_due"], date(2026, 4, 4))
        self.assertEqual(values["currency_code"], "GBP")
        self.assertEqual(values["iban"], "GB29NWBK60161331926819")
        self.assertEqual(values["payment_reference"], "XR-2026-7")
        self.assertEqual(values["payment_terms"], "Net 30")
        self.assertEqual(values["purchase_order"], "04011000-12345-34")

    def test_ubl_amounts_use_tax_exclusive_and_inclusive_totals(self):
        values = self.parser._parse(UBL_XML)
        self.assertEqual(values["amount_untaxed"], 100.0)
        self.assertEqual(values["amount_tax"], 20.0)
        self.assertEqual(values["amount_total"], 120.0)

    def test_ubl_prefers_legal_entity_name(self):
        self.assertEqual(
            self.parser._parse(UBL_XML)["partner_name"], "Supplier Holdings Ltd"
        )

    def test_ubl_prefers_the_vat_tax_scheme(self):
        # A German seller sends the Steuernummer under scheme FC as well.
        self.assertEqual(self.parser._parse(UBL_XML)["partner_vat"], "GB123456789")

    # ------------------------------------------------------------------
    # PDF containers
    # ------------------------------------------------------------------

    def test_xml_embedded_in_a_pdf_is_found(self):
        pdf = build_pdf([("factur-x.xml", CII_XML)])
        self.assertEqual(
            self.parser._parse(pdf)["invoice_number"], "RE-2026-0042"
        )

    def test_embedded_xml_under_a_nonstandard_name_is_still_found(self):
        pdf = build_pdf([("invoice-data.xml", UBL_XML)])
        self.assertEqual(self.parser._parse(pdf)["invoice_number"], "XR-2026-7")

    def test_standard_name_wins_over_other_embedded_files(self):
        pdf = build_pdf([("something-else.xml", UBL_XML), ("factur-x.xml", CII_XML)])
        self.assertEqual(self.parser._parse(pdf)["invoice_number"], "RE-2026-0042")

    def test_a_pdf_with_bytes_before_its_header_is_still_read(self):
        pdf = b"\n\n" + build_pdf([("factur-x.xml", CII_XML)])
        self.assertEqual(self.parser._parse(pdf)["invoice_number"], "RE-2026-0042")

    def test_pdf_without_an_embedded_invoice_is_not_an_einvoice(self):
        self.assertIsNone(self.parser._parse(build_pdf()))

    def test_pdf_with_an_unrelated_attachment_is_not_an_einvoice(self):
        pdf = build_pdf([("notes.xml", b"<notes><note>hi</note></notes>")])
        self.assertIsNone(self.parser._parse(pdf))

    # ------------------------------------------------------------------
    # Rejections
    # ------------------------------------------------------------------

    def test_unparseable_content_is_not_an_einvoice(self):
        self.assertIsNone(self.parser._parse(b"just some scanned bytes"))

    def test_malformed_pdf_is_not_an_einvoice(self):
        self.assertIsNone(self.parser._parse(b"%PDF-1.7 truncated"))

    def test_xml_of_another_kind_is_not_an_einvoice(self):
        self.assertIsNone(self.parser._parse(b"<?xml version='1.0'?><order/>"))

    def test_missing_header_elements_are_absent_rather_than_empty(self):
        minimal = (
            b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:'
            b'standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact'
            b':data:standard:ReusableAggregateBusinessInformationEntity:100">'
            b"<rsm:ExchangedDocument><ram:ID>ONLY-ID</ram:ID>"
            b"</rsm:ExchangedDocument></rsm:CrossIndustryInvoice>"
        )
        values = self.parser._parse(minimal)
        # document_type and lines are always reported; nothing else is invented.
        self.assertEqual(
            values,
            {"invoice_number": "ONLY-ID", "document_type": "invoice", "lines": []},
        )

    def test_external_entities_are_not_resolved(self):
        # An invoice arriving by mail is untrusted input.
        payload = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:'
            b'standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact'
            b':data:standard:ReusableAggregateBusinessInformationEntity:100">'
            b"<rsm:ExchangedDocument><ram:ID>&xxe;</ram:ID>"
            b"</rsm:ExchangedDocument></rsm:CrossIndustryInvoice>"
        )
        values = self.parser._parse(payload)
        self.assertNotIn("root:", (values or {}).get("invoice_number") or "")

    # ------------------------------------------------------------------
    # Document type
    # ------------------------------------------------------------------

    def test_cii_type_code_380_is_an_invoice(self):
        self.assertEqual(self.parser._parse(CII_XML)["document_type"], "invoice")

    def test_cii_type_code_381_is_a_credit_note(self):
        self.assertEqual(
            self.parser._parse(CII_CREDIT_NOTE_XML)["document_type"], "credit_note"
        )

    def test_a_credit_note_keeps_its_amounts_positive(self):
        # EN16931 credit notes state positive amounts; the type carries the sign.
        self.assertEqual(self.parser._parse(CII_CREDIT_NOTE_XML)["amount_total"], 529.87)

    def test_ubl_credit_note_root_is_a_credit_note(self):
        values = self.parser._parse(UBL_CREDIT_NOTE_XML)
        self.assertEqual(values["document_type"], "credit_note")
        self.assertEqual(values["invoice_number"], "XR-2026-7")

    def test_ubl_invoice_declaring_type_code_381_is_a_credit_note(self):
        self.assertEqual(
            self.parser._parse(UBL_TYPECODE_CREDIT_NOTE_XML)["document_type"],
            "credit_note",
        )

    def test_ubl_invoice_is_an_invoice(self):
        self.assertEqual(self.parser._parse(UBL_XML)["document_type"], "invoice")

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    def test_cii_lines(self):
        lines = self.parser._parse(CII_XML)["lines"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            {
                "sequence": 10,
                "name": "Trennblätter A4",
                "product_code": "TB100A4",
                "quantity": 20.0,
                "price_unit": 9.9,
                "tax_rate": 19.0,
                "amount": 198.0,
                "uom": "H87",
            },
        )
        self.assertEqual(lines[1]["name"], "Joghurt Banane")
        self.assertEqual(lines[1]["tax_rate"], 7.0)
        self.assertEqual(lines[1]["sequence"], 20)

    def test_cii_lines_add_up_to_the_untaxed_amount(self):
        values = self.parser._parse(CII_XML)
        self.assertEqual(
            sum(line["amount"] for line in values["lines"]), values["amount_untaxed"]
        )

    def test_ubl_lines(self):
        lines = self.parser._parse(UBL_XML)["lines"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["name"], "Consulting")
        self.assertEqual(lines[0]["product_code"], "SVC-1")
        self.assertEqual(lines[0]["quantity"], 20.0)
        self.assertEqual(lines[0]["uom"], "H87")
        self.assertEqual(lines[0]["price_unit"], 5.0)
        self.assertEqual(lines[0]["tax_rate"], 20.0)
        self.assertEqual(lines[0]["amount"], 100.0)

    def test_ubl_credit_note_lines_use_the_credited_quantity(self):
        lines = self.parser._parse(UBL_CREDIT_NOTE_XML)["lines"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["quantity"], 20.0)
        self.assertEqual(lines[0]["uom"], "H87")

    def test_lines_survive_the_pdf_container(self):
        pdf = build_pdf([("factur-x.xml", CII_XML)])
        self.assertEqual(len(self.parser._parse(pdf)["lines"]), 2)

    def test_a_document_without_lines_reports_an_empty_list(self):
        minimal = (
            b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:'
            b'standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact'
            b':data:standard:ReusableAggregateBusinessInformationEntity:100">'
            b"<rsm:ExchangedDocument><ram:ID>NO-LINES</ram:ID>"
            b"</rsm:ExchangedDocument></rsm:CrossIndustryInvoice>"
        )
        self.assertEqual(self.parser._parse(minimal)["lines"], [])
