import logging
from datetime import datetime
from io import BytesIO

from lxml import etree
from odoo import models
from odoo.tools.pdf import PdfReader

_logger = logging.getLogger(__name__)

# Embedded-file names the standards prescribe, tried before anything else in
# the PDF. ZUGFeRD 2.1 renamed zugferd-invoice.xml to factur-x.xml; XRechnung
# and Peppol senders occasionally use their own name, which is why every other
# embedded file is still tried afterwards.
KNOWN_XML_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "cii.xml")

# Element paths are namespace-wildcarded (`{*}`) so one set covers Factur-X,
# ZUGFeRD 2.x and XRechnung CII, whose namespaces differ by profile and
# version. The first path that yields text wins.
CII_PATHS = {
    "invoice_number": ["./{*}ExchangedDocument/{*}ID"],
    "invoice_date": ["./{*}ExchangedDocument/{*}IssueDateTime/{*}DateTimeString"],
    "date_due": [".//{*}SpecifiedTradePaymentTerms/{*}DueDateDateTime/{*}DateTimeString"],
    "partner_name": [".//{*}SellerTradeParty/{*}Name"],
    "partner_vat": [
        ".//{*}SellerTradeParty/{*}SpecifiedTaxRegistration/{*}ID[@schemeID='VA']",
        ".//{*}SellerTradeParty/{*}SpecifiedTaxRegistration/{*}ID",
    ],
    "currency_code": [".//{*}InvoiceCurrencyCode"],
    "payment_reference": [
        ".//{*}ApplicableHeaderTradeSettlement/{*}PaymentReference",
    ],
    "iban": [".//{*}PayeePartyCreditorFinancialAccount/{*}IBANID"],
    "purchase_order": [
        ".//{*}BuyerOrderReferencedDocument/{*}IssuerAssignedID",
        ".//{*}ApplicableHeaderTradeAgreement/{*}BuyerReference",
    ],
    "payment_terms": [".//{*}SpecifiedTradePaymentTerms/{*}Description"],
    "amount_untaxed": [
        ".//{*}SpecifiedTradeSettlementHeaderMonetarySummation/{*}TaxBasisTotalAmount",
    ],
    "amount_tax": [
        ".//{*}SpecifiedTradeSettlementHeaderMonetarySummation/{*}TaxTotalAmount",
    ],
    "amount_total": [
        ".//{*}SpecifiedTradeSettlementHeaderMonetarySummation/{*}GrandTotalAmount",
    ],
}

UBL_PATHS = {
    "invoice_number": ["./{*}ID"],
    "invoice_date": ["./{*}IssueDate"],
    "date_due": ["./{*}DueDate", ".//{*}PaymentMeans/{*}PaymentDueDate"],
    "partner_name": [
        ".//{*}AccountingSupplierParty/{*}Party/{*}PartyLegalEntity/{*}RegistrationName",
        ".//{*}AccountingSupplierParty/{*}Party/{*}PartyName/{*}Name",
    ],
    "currency_code": ["./{*}DocumentCurrencyCode"],
    "payment_reference": [".//{*}PaymentMeans/{*}PaymentID"],
    "iban": [".//{*}PaymentMeans/{*}PayeeFinancialAccount/{*}ID"],
    "purchase_order": ["./{*}OrderReference/{*}ID", "./{*}BuyerReference"],
    "payment_terms": ["./{*}PaymentTerms/{*}Note"],
    "amount_untaxed": ["./{*}LegalMonetaryTotal/{*}TaxExclusiveAmount"],
    "amount_tax": ["./{*}TaxTotal/{*}TaxAmount"],
    "amount_total": [
        "./{*}LegalMonetaryTotal/{*}TaxInclusiveAmount",
        "./{*}LegalMonetaryTotal/{*}PayableAmount",
    ],
}

# UNTDID 1001 document type codes that make the document a credit note:
# 381 credit note, 261 self-billed credit note, 396 factored credit note.
# Everything else in the EN16931 code list is an invoice of some kind.
CREDIT_NOTE_CODES = ("381", "261", "396")

# One line item. `uom` keeps whatever the document states — a UN/ECE Rec 20
# code in CII and UBL ("H87"), free text from OCR ("hours").
CII_LINE_PATHS = {
    "name": [
        "./{*}SpecifiedTradeProduct/{*}Name",
        "./{*}SpecifiedTradeProduct/{*}Description",
    ],
    "product_code": ["./{*}SpecifiedTradeProduct/{*}SellerAssignedID"],
    "quantity": ["./{*}SpecifiedLineTradeDelivery/{*}BilledQuantity"],
    "price_unit": [
        "./{*}SpecifiedLineTradeAgreement/{*}NetPriceProductTradePrice/{*}ChargeAmount",
        "./{*}SpecifiedLineTradeAgreement/{*}GrossPriceProductTradePrice/{*}ChargeAmount",
    ],
    "tax_rate": [
        "./{*}SpecifiedLineTradeSettlement/{*}ApplicableTradeTax/{*}RateApplicablePercent"
    ],
    "amount": [
        "./{*}SpecifiedLineTradeSettlement"
        "/{*}SpecifiedTradeSettlementLineMonetarySummation/{*}LineTotalAmount"
    ],
}
CII_LINE_QUANTITY_PATH = "./{*}SpecifiedLineTradeDelivery/{*}BilledQuantity"

UBL_LINE_PATHS = {
    "name": ["./{*}Item/{*}Name", "./{*}Item/{*}Description"],
    "product_code": ["./{*}Item/{*}SellersItemIdentification/{*}ID"],
    "quantity": ["./{*}InvoicedQuantity", "./{*}CreditedQuantity"],
    "price_unit": ["./{*}Price/{*}PriceAmount"],
    "tax_rate": ["./{*}Item/{*}ClassifiedTaxCategory/{*}Percent"],
    "amount": ["./{*}LineExtensionAmount"],
}
UBL_LINE_QUANTITY_PATHS = ("./{*}InvoicedQuantity", "./{*}CreditedQuantity")

LINE_NUMBER_FIELDS = ("quantity", "price_unit", "tax_rate", "amount")

AMOUNT_FIELDS = ("amount_untaxed", "amount_tax", "amount_total")
DATE_FIELDS = ("invoice_date", "date_due")
# CII carries dates as UNCL2379 format 102, i.e. YYYYMMDD. UBL uses xs:date.
CII_DATE_FORMAT = "%Y%m%d"
UBL_DATE_FORMAT = "%Y-%m-%d"


class InvoiceEinvoiceParser(models.AbstractModel):
    """Reads invoice header fields out of a structured e-invoice.

    Handles CII (ZUGFeRD 2.x, Factur-X, XRechnung CII) and UBL 2.1 (XRechnung
    UBL, Peppol BIS Billing 3.0), either as a standalone XML file or embedded
    in a PDF/A-3 container. ZUGFeRD 1.0 uses different element names and is not
    supported.

    Header fields only — line items are deliberately out of scope.
    """

    _name = "invoice.einvoice.parser"
    _description = "E-invoice field reader (CII / UBL)"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _parse(self, content):
        """Read invoice values out of `content` (raw XML or PDF bytes).

        Returns a dict of field values, or None when `content` carries no
        e-invoice this parser understands. Values absent from the document are
        absent from the dict; nothing is invented.
        """
        tree = self._get_tree(content)
        if tree is None:
            return None
        root = etree.QName(tree).localname
        if root == "CrossIndustryInvoice":
            values = self._collect(tree, CII_PATHS, CII_DATE_FORMAT)
            type_code = tree.findtext("./{*}ExchangedDocument/{*}TypeCode")
            values["document_type"] = self._document_type(type_code)
            values["lines"] = self._collect_lines(
                tree,
                "./{*}SupplyChainTradeTransaction/{*}IncludedSupplyChainTradeLineItem",
                CII_LINE_PATHS,
                (CII_LINE_QUANTITY_PATH,),
            )
            return values
        if root in ("Invoice", "CreditNote"):
            values = self._collect(tree, UBL_PATHS, UBL_DATE_FORMAT)
            vat = self._ubl_seller_vat(tree)
            if vat:
                values["partner_vat"] = vat
            # A UBL CreditNote is one by its root element; an Invoice can still
            # declare itself one through InvoiceTypeCode.
            type_code = tree.findtext("./{*}InvoiceTypeCode")
            values["document_type"] = (
                "credit_note" if root == "CreditNote" else self._document_type(type_code)
            )
            values["lines"] = self._collect_lines(
                tree,
                "./{*}InvoiceLine" if root == "Invoice" else "./{*}CreditNoteLine",
                UBL_LINE_PATHS,
                UBL_LINE_QUANTITY_PATHS,
            )
            return values
        return None

    def _document_type(self, type_code):
        """`credit_note` for the UNTDID codes that mean one, else `invoice`."""
        if type_code and type_code.strip() in CREDIT_NOTE_CODES:
            return "credit_note"
        return "invoice"

    # ------------------------------------------------------------------
    # Locating the XML
    # ------------------------------------------------------------------

    def _get_tree(self, content):
        """The e-invoice XML root of `content`, from the file or from a PDF."""
        # Some generators emit bytes ahead of the header, and pypdf recovers
        # from that, so look for the header near the start rather than
        # requiring it at offset 0 and sending the invoice to OCR instead.
        if content[:1024].find(b"%PDF-") >= 0:
            return self._get_tree_from_pdf(content)
        return self._parse_xml(content)

    def _get_tree_from_pdf(self, content):
        """First embedded file in a PDF/A-3 that parses as an e-invoice."""
        try:
            attachments = PdfReader(BytesIO(content), strict=False).attachments
        except Exception as e:
            _logger.info(
                "invoice_inbound_pdf_unreadable",
                extra={"event": "invoice_inbound_pdf_unreadable", "error": str(e)},
            )
            return None
        # Standard names first, then everything else: senders do not always
        # follow the naming rule, but a correctly named file is authoritative.
        names = sorted(
            attachments, key=lambda n: (n.lower() not in KNOWN_XML_NAMES, n.lower())
        )
        for name in names:
            for payload in attachments[name] or []:
                tree = self._parse_xml(payload)
                if tree is not None and etree.QName(tree).localname in (
                    "CrossIndustryInvoice",
                    "Invoice",
                    "CreditNote",
                ):
                    return tree
        return None

    def _parse_xml(self, content):
        """Parse untrusted XML with entity resolution and network access off."""
        parser = etree.XMLParser(
            resolve_entities=False, no_network=True, load_dtd=False
        )
        try:
            return etree.fromstring(content, parser=parser)
        except etree.XMLSyntaxError:
            return None
        except ValueError:
            # lxml refuses a str carrying an encoding declaration.
            return None

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _ubl_seller_vat(self, tree):
        """Seller VAT id, preferring the registration in the VAT tax scheme.

        UBL carries one PartyTaxScheme per registration and a German seller
        commonly sends both the Steuernummer (scheme `FC`) and the VAT id
        (scheme `VAT`). ElementPath cannot express that nested condition, so
        the nodes are walked here. Falls back to the first registration found
        for sellers that report only one.
        """
        registrations = tree.findall(
            ".//{*}AccountingSupplierParty/{*}Party/{*}PartyTaxScheme"
        )
        fallback = None
        for registration in registrations:
            company_id = (registration.findtext("{*}CompanyID") or "").strip()
            if not company_id:
                continue
            scheme = (registration.findtext("{*}TaxScheme/{*}ID") or "").strip()
            if scheme.upper() == "VAT":
                return company_id
            fallback = fallback or company_id
        return fallback

    def _first_text(self, tree, paths):
        for path in paths:
            text = tree.findtext(path)
            if text and text.strip():
                return text.strip()
        return None

    def _collect_lines(self, tree, line_path, paths, quantity_paths):
        """Line items of the document, in document order.

        The unit of measure travels as an attribute on the quantity element
        rather than as its own element, so it is read separately.
        """
        lines = []
        for sequence, node in enumerate(tree.findall(line_path), start=1):
            values = {"sequence": sequence * 10}
            for field, xpaths in paths.items():
                text = self._first_text(node, xpaths)
                if text is None:
                    continue
                if field in LINE_NUMBER_FIELDS:
                    try:
                        values[field] = float(text)
                    except ValueError:
                        continue
                else:
                    values[field] = text
            for quantity_path in quantity_paths:
                element = node.find(quantity_path)
                if element is not None and element.get("unitCode"):
                    values["uom"] = element.get("unitCode")
                    break
            if len(values) > 1:
                lines.append(values)
        return lines

    def _collect(self, tree, paths, date_format):
        values = {}
        for field, xpaths in paths.items():
            text = self._first_text(tree, xpaths)
            if text is None:
                continue
            if field in AMOUNT_FIELDS:
                try:
                    values[field] = float(text)
                except ValueError:
                    continue
            elif field in DATE_FIELDS:
                try:
                    values[field] = datetime.strptime(text, date_format).date()
                except ValueError:
                    continue
            else:
                values[field] = text
        return values
