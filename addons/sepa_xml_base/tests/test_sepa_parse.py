from datetime import date, datetime
from decimal import Decimal

from odoo.tests.common import tagged

from .common import (
    CREDITOR,
    CREDITOR_ID,
    DEBTOR,
    SepaCase,
    credit_transfer_payload,
    direct_debit_payload,
)

PREFIXED_LEGACY_TRANSFER = """<?xml version="1.0" encoding="UTF-8"?>
<pain:Document xmlns:pain="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <pain:CstmrCdtTrfInitn>
    <pain:GrpHdr>
      <pain:MsgId>BANK-0815</pain:MsgId>
      <pain:CreDtTm>2026-08-20T08:00:00</pain:CreDtTm>
      <pain:NbOfTxs>1</pain:NbOfTxs>
      <pain:CtrlSum>25.00</pain:CtrlSum>
      <pain:InitgPty><pain:Nm>Muster GmbH</pain:Nm></pain:InitgPty>
    </pain:GrpHdr>
    <pain:PmtInf>
      <pain:PmtInfId>PMT-0815</pain:PmtInfId>
      <pain:PmtMtd>TRF</pain:PmtMtd>
      <pain:NbOfTxs>1</pain:NbOfTxs>
      <pain:CtrlSum>25.00</pain:CtrlSum>
      <pain:ReqdExctnDt>2026-08-21</pain:ReqdExctnDt>
      <pain:Dbtr><pain:Nm>Muster GmbH</pain:Nm></pain:Dbtr>
      <pain:DbtrAcct>
        <pain:Id><pain:IBAN>DE89370400440532013000</pain:IBAN></pain:Id>
      </pain:DbtrAcct>
      <pain:DbtrAgt>
        <pain:FinInstnId><pain:BIC>COBADEFFXXX</pain:BIC></pain:FinInstnId>
      </pain:DbtrAgt>
      <pain:ChrgBr>SLEV</pain:ChrgBr>
      <pain:CdtTrfTxInf>
        <pain:PmtId><pain:EndToEndId>E2E-1</pain:EndToEndId></pain:PmtId>
        <pain:Amt><pain:InstdAmt Ccy="EUR">25.00</pain:InstdAmt></pain:Amt>
        <pain:Cdtr><pain:Nm>Lieferant AG</pain:Nm></pain:Cdtr>
        <pain:CdtrAcct>
          <pain:Id><pain:IBAN>DE02120300000000202051</pain:IBAN></pain:Id>
        </pain:CdtrAcct>
        <pain:RmtInf><pain:Ustrd>Rechnung 7</pain:Ustrd></pain:RmtInf>
      </pain:CdtTrfTxInf>
    </pain:PmtInf>
  </pain:CstmrCdtTrfInitn>
</pain:Document>
"""

ENTITY_ATTACK = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE Document [<!ENTITY leak SYSTEM "file:///etc/passwd">]>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
  <CstmrCdtTrfInitn>
    <GrpHdr><MsgId>&leak;</MsgId></GrpHdr>
  </CstmrCdtTrfInitn>
</Document>
"""


@tagged("post_install", "-at_install")
class TestSepaParse(SepaCase):
    def parse(self, source):
        ok, result = self.sepa._parse(source)
        self.assertTrue(ok, result)
        return result

    def test_parse_credit_transfer(self):
        ok, xml = self.sepa._build_credit_transfer(credit_transfer_payload())
        self.assertTrue(ok, xml)
        document = self.parse(xml)
        self.assertEqual(document["document_type"], "credit_transfer")
        self.assertEqual(document["version"], "pain.001.001.09")
        header = document["group_header"]
        self.assertEqual(header["message_id"], "MSG-CT-1")
        self.assertEqual(
            header["creation_date_time"],
            datetime.fromisoformat("2026-08-23T10:15:30+00:00"),
        )
        self.assertEqual(header["number_of_transactions"], 2)
        self.assertEqual(header["control_sum"], Decimal("1244.56"))
        self.assertEqual(header["initiating_party"]["identifier"], "DE1234567")

        payment = document["payments"][0]
        self.assertEqual(payment["payment_id"], "PMT-1")
        self.assertEqual(payment["payment_method"], "TRF")
        self.assertIs(payment["batch_booking"], True)
        self.assertEqual(payment["requested_date"], date(2026, 8, 25))
        self.assertEqual(payment["charge_bearer"], "SLEV")
        self.assertEqual(payment["debtor"]["iban"], DEBTOR["iban"])
        self.assertEqual(payment["debtor"]["bic"], DEBTOR["bic"])
        self.assertEqual(payment["debtor"]["country"], "DE")
        self.assertEqual(payment["debtor"]["address_lines"], DEBTOR["address_lines"])

        first, second = payment["transactions"]
        self.assertEqual(first["end_to_end_id"], "INV-2026-0001")
        self.assertEqual(first["amount"], Decimal("1234.56"))
        self.assertEqual(first["currency"], "EUR")
        self.assertEqual(first["creditor"]["name"], CREDITOR["name"])
        self.assertEqual(first["remittance_info"], "Rechnung 2026-0001")
        self.assertEqual(second["end_to_end_id"], "NOTPROVIDED")
        self.assertEqual(second["creditor_reference"], "RF18539007547034")
        self.assertEqual(second["purpose"], "GDDS")
        self.assertNotIn("bic", second["creditor"])

    def test_parse_direct_debit(self):
        ok, xml = self.sepa._build_direct_debit(direct_debit_payload())
        self.assertTrue(ok, xml)
        document = self.parse(xml)
        self.assertEqual(document["document_type"], "direct_debit")
        self.assertEqual(document["version"], "pain.008.001.08")
        payment = document["payments"][0]
        self.assertEqual(payment["payment_method"], "DD")
        self.assertEqual(payment["sequence_type"], "RCUR")
        self.assertEqual(payment["local_instrument"], "CORE")
        self.assertEqual(payment["creditor_scheme_id"], CREDITOR_ID)
        self.assertEqual(payment["requested_date"], date(2026, 9, 1))
        transaction = payment["transactions"][0]
        self.assertEqual(transaction["amount"], Decimal("49.90"))
        self.assertEqual(transaction["debtor"]["iban"], DEBTOR["iban"])
        self.assertEqual(transaction["mandate"]["id"], "MNDT-0001")
        self.assertEqual(transaction["mandate"]["signature_date"], date(2024, 2, 1))
        self.assertIs(transaction["mandate"]["amendment_indicator"], False)

    def test_parse_mandate_amendment(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["mandate"]["amendment"] = {
            "original_mandate_id": "OLD-1",
            "same_mandate_new_debtor_account": True,
        }
        for version in ("pain.008.001.08", "pain.008.001.02"):
            with self.subTest(version):
                ok, xml = self.sepa._build_direct_debit(payload, version=version)
                self.assertTrue(ok, xml)
                amendment = self.parse(xml)["payments"][0]["transactions"][0][
                    "mandate"
                ]["amendment"]
                self.assertEqual(amendment["original_mandate_id"], "OLD-1")
                self.assertIs(amendment["same_mandate_new_debtor_account"], True)

    def test_round_trip_is_stable(self):
        for label, payload, build in (
            (
                "credit_transfer",
                credit_transfer_payload(),
                self.sepa._build_credit_transfer,
            ),
            ("direct_debit", direct_debit_payload(), self.sepa._build_direct_debit),
        ):
            with self.subTest(label):
                ok, first = build(payload)
                self.assertTrue(ok, first)
                ok, again = build(self.parse(first))
                self.assertTrue(ok, again)
                self.assertEqual(first, again)

    def test_parse_prefixed_legacy_document(self):
        document = self.parse(PREFIXED_LEGACY_TRANSFER)
        self.assertEqual(document["version"], "pain.001.001.03")
        self.assertEqual(document["group_header"]["message_id"], "BANK-0815")
        payment = document["payments"][0]
        self.assertEqual(payment["requested_date"], date(2026, 8, 21))
        self.assertEqual(payment["debtor"]["bic"], "COBADEFFXXX")
        transaction = payment["transactions"][0]
        self.assertEqual(transaction["amount"], Decimal("25.00"))
        self.assertEqual(transaction["remittance_info"], "Rechnung 7")
        self.assertNotIn("mandate", transaction)

    def test_parsed_document_can_be_rewritten_in_another_version(self):
        document = self.parse(PREFIXED_LEGACY_TRANSFER)
        root = self.build(document, version="pain.001.001.09")
        self.assertEqual(self.text(root, "//n:GrpHdr/n:MsgId"), "BANK-0815")
        self.assertEqual(self.text(root, "//n:PmtInf/n:ReqdExctnDt/n:Dt"), "2026-08-21")
        self.assertEqual(
            self.text(root, "//n:DbtrAgt/n:FinInstnId/n:BICFI"), "COBADEFFXXX"
        )

    def test_parse_accepts_bytes_and_text(self):
        ok, xml = self.sepa._build_credit_transfer(credit_transfer_payload())
        self.assertTrue(ok, xml)
        self.assertEqual(
            self.parse(xml)["group_header"]["message_id"],
            self.parse(xml.decode())["group_header"]["message_id"],
        )

    def test_rejected_documents(self):
        cases = {
            "malformed": (b"<Document", "malformed XML"),
            "other_schema": (
                b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"/>',
                "not a SEPA",
            ),
            "no_namespace": (b"<Document><GrpHdr/></Document>", "not an ISO 20022"),
            "mismatched_body": (
                (
                    b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">'
                    b"<CstmrDrctDbtInitn/></Document>"
                ),
                "does not match",
            ),
            "no_header": (
                (
                    b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">'
                    b"<CstmrCdtTrfInitn/></Document>"
                ),
                "no GrpHdr",
            ),
        }
        for label, (source, expected) in cases.items():
            with self.subTest(label):
                ok, error = self.sepa._parse(source)
                self.assertFalse(ok)
                self.assertIn(expected, error)

    def test_external_entities_are_not_resolved(self):
        ok, result = self.sepa._parse(ENTITY_ATTACK)
        self.assertNotIn("root:", str(result))
        if ok:
            self.assertFalse(result["group_header"].get("message_id"))

    def test_consumer_helpers(self):
        self.assertEqual(
            self.sepa._validate_iban("de89 3704 0044 0532 0130 00"),
            (True, DEBTOR["iban"]),
        )
        ok, error = self.sepa._validate_iban("DE00")
        self.assertFalse(ok)
        self.assertIn("IBAN", error)
        self.assertEqual(
            self.sepa._validate_creditor_identifier(CREDITOR_ID), (True, CREDITOR_ID)
        )
        self.assertEqual(self.sepa._sanitize_text("Müller & Co", 8), "Mueller")
