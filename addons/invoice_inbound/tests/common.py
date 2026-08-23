import io

from odoo.tools.pdf import PdfWriter

CII_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>RE-2026-0042</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260304</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:BuyerReference>04011000-12345-34</ram:BuyerReference>
      <ram:SellerTradeParty>
        <ram:Name>Lieferant GmbH</ram:Name>
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="FC">201/113/40209</ram:ID>
        </ram:SpecifiedTaxRegistration>
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="VA">DE123456789</ram:ID>
        </ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerOrderReferencedDocument>
        <ram:IssuerAssignedID>PO-9182</ram:IssuerAssignedID>
      </ram:BuyerOrderReferencedDocument>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:PaymentReference>RE-2026-0042</ram:PaymentReference>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:PayeePartyCreditorFinancialAccount>
          <ram:IBANID>DE02120300000000202051</ram:IBANID>
        </ram:PayeePartyCreditorFinancialAccount>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>Zahlbar innerhalb 30 Tagen netto</ram:Description>
        <ram:DueDateDateTime>
          <udt:DateTimeString format="102">20260403</udt:DateTimeString>
        </ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>473.00</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>473.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">56.87</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>529.87</ram:GrandTotalAmount>
        <ram:DuePayableAmount>529.87</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct>
        <ram:SellerAssignedID>TB100A4</ram:SellerAssignedID>
        <ram:Name>Trennbl\xc3\xa4tter A4</ram:Name>
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>9.9000</ram:ChargeAmount>
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="H87">20.0000</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax>
          <ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>
        </ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>198.00</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct>
        <ram:SellerAssignedID>ARNR2</ram:SellerAssignedID>
        <ram:Name>Joghurt Banane</ram:Name>
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>5.5000</ram:ChargeAmount>
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="H87">50.0000</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax>
          <ram:RateApplicablePercent>7.00</ram:RateApplicablePercent>
        </ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>275.00</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""

# Same document as a credit note: UNTDID type code 381, amounts still positive.
CII_CREDIT_NOTE_XML = CII_XML.replace(
    b"<ram:TypeCode>380</ram:TypeCode>", b"<ram:TypeCode>381</ram:TypeCode>"
)

UBL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>XR-2026-7</cbc:ID>
  <cbc:IssueDate>2026-03-05</cbc:IssueDate>
  <cbc:DueDate>2026-04-04</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>GBP</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>04011000-12345-34</cbc:BuyerReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Trading Name Ltd</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>201/113/40209</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>FC</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>GB123456789</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>Supplier Holdings Ltd</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:PaymentMeans>
    <cbc:PaymentID>XR-2026-7</cbc:PaymentID>
    <cac:PayeeFinancialAccount><cbc:ID>GB29NWBK60161331926819</cbc:ID></cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:PaymentTerms><cbc:Note>Net 30</cbc:Note></cac:PaymentTerms>
  <cac:TaxTotal><cbc:TaxAmount currencyID="GBP">20.00</cbc:TaxAmount></cac:TaxTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="H87">20</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="GBP">100.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>Consulting</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>SVC-1</cbc:ID></cac:SellersItemIdentification>
      <cac:ClassifiedTaxCategory><cbc:Percent>20</cbc:Percent></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="GBP">5.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="GBP">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="GBP">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="GBP">120.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="GBP">120.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""


def build_pdf(attachments=()):
    """A one-page PDF carrying `attachments` as (name, bytes) pairs."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    for name, payload in attachments:
        writer.add_attachment(name, payload)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# prebuilt-invoice response for a scan that carries no e-invoice XML.
DI_ANALYZE_RESULT = {
    "modelId": "prebuilt-invoice",
    "documents": [
        {
            "docType": "invoice",
            "confidence": 0.93,
            "fields": {
                "VendorName": {
                    "type": "string",
                    "valueString": "Scan Supplies GmbH",
                    "confidence": 0.96,
                },
                "VendorTaxId": {
                    "type": "string",
                    "valueString": "DE999888777",
                    "confidence": 0.9,
                },
                "InvoiceId": {
                    "type": "string",
                    "valueString": "SC-5501",
                    "confidence": 0.95,
                },
                "InvoiceDate": {
                    "type": "date",
                    "valueDate": "2026-02-01",
                    "confidence": 0.92,
                },
                "DueDate": {"type": "date", "valueDate": "2026-03-03", "confidence": 0.9},
                "PurchaseOrder": {
                    "type": "string",
                    "valueString": "PO-7788",
                    "confidence": 0.7,
                },
                "PaymentTerm": {"type": "string", "valueString": "Net 30", "confidence": 0.6},
                "SubTotal": {
                    "type": "currency",
                    "valueCurrency": {"amount": 200.0, "currencyCode": "EUR"},
                    "confidence": 0.89,
                },
                "TotalTax": {
                    "type": "currency",
                    "valueCurrency": {"amount": 38.0, "currencyCode": "EUR"},
                    "confidence": 0.87,
                },
                "InvoiceTotal": {
                    "type": "currency",
                    "valueCurrency": {"amount": 238.0, "currencyCode": "EUR"},
                    "confidence": 0.91,
                },
                "PaymentDetails": {
                    "type": "array",
                    "confidence": 0.75,
                    "valueArray": [
                        {
                            "type": "object",
                            "valueObject": {
                                "IBAN": {
                                    "type": "string",
                                    "valueString": "DE44500105175407324931",
                                }
                            },
                        }
                    ],
                },
            },
        }
    ],
}


# A UBL credit note: different root element, CreditNoteLine, CreditedQuantity.
UBL_CREDIT_NOTE_XML = (
    UBL_XML.replace(b"<Invoice ", b"<CreditNote ")
    .replace(b"</Invoice>", b"</CreditNote>")
    .replace(b":Invoice-2", b":CreditNote-2")
    .replace(b"cac:InvoiceLine", b"cac:CreditNoteLine")
    .replace(b"cbc:InvoicedQuantity", b"cbc:CreditedQuantity")
    .replace(b"<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>", b"")
)

# A UBL Invoice that declares itself a credit note through its type code.
UBL_TYPECODE_CREDIT_NOTE_XML = UBL_XML.replace(
    b"<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
    b"<cbc:InvoiceTypeCode>381</cbc:InvoiceTypeCode>",
)

# prebuilt-invoice Items, as the service encodes them.
DI_ITEMS_FIELD = {
    "type": "array",
    "confidence": 0.82,
    "valueArray": [
        {
            "type": "object",
            "valueObject": {
                "Description": {"type": "string", "valueString": "Consulting Services"},
                "ProductCode": {"type": "string", "valueString": "A123"},
                "Quantity": {"type": "number", "valueNumber": 2},
                "Unit": {"type": "string", "valueString": "hours"},
                "UnitPrice": {
                    "type": "currency",
                    "valueCurrency": {"amount": 30.0, "currencyCode": "EUR"},
                },
                "TaxRate": {"type": "string", "valueString": "19 %"},
                "Amount": {
                    "type": "currency",
                    "valueCurrency": {"amount": 60.0, "currencyCode": "EUR"},
                },
            },
        },
        {
            "type": "object",
            "valueObject": {
                "Description": {"type": "string", "valueString": "Travel"},
                "Amount": {
                    "type": "currency",
                    "valueCurrency": {"amount": 140.0, "currencyCode": "EUR"},
                },
            },
        },
    ],
}

DI_ANALYZE_RESULT["documents"][0]["fields"]["Items"] = DI_ITEMS_FIELD


def di_credit_note_result():
    """The same analysis with negative totals, which is all OCR gives us."""
    import copy

    result = copy.deepcopy(DI_ANALYZE_RESULT)
    fields = result["documents"][0]["fields"]
    for name in ("SubTotal", "TotalTax", "InvoiceTotal"):
        fields[name]["valueCurrency"]["amount"] *= -1
    return result
