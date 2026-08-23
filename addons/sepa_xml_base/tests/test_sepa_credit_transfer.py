from lxml import etree
from odoo.tests.common import tagged

from .common import CREDITOR, DEBTOR, SepaCase, credit_transfer_payload


@tagged("post_install", "-at_install")
class TestSepaCreditTransfer(SepaCase):
    def test_document_shape(self):
        root = self.build(credit_transfer_payload())
        self.assertEqual(
            root.nsmap[None], "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
        )
        self.assertEqual(etree.QName(root).localname, "Document")
        self.assertEqual(
            root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"),
            "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09 pain.001.001.09.xsd",
        )
        self.assertEqual(len(self.nodes(root, "/n:Document/n:CstmrCdtTrfInitn")), 1)

    def test_group_header(self):
        root = self.build(credit_transfer_payload())
        self.assertEqual(self.text(root, "//n:GrpHdr/n:MsgId"), "MSG-CT-1")
        self.assertEqual(
            self.text(root, "//n:GrpHdr/n:CreDtTm"), "2026-08-23T10:15:30Z"
        )
        self.assertEqual(self.text(root, "//n:GrpHdr/n:NbOfTxs"), "2")
        self.assertEqual(self.text(root, "//n:GrpHdr/n:CtrlSum"), "1244.56")
        self.assertEqual(self.text(root, "//n:GrpHdr/n:InitgPty/n:Nm"), "Muster GmbH")
        self.assertEqual(
            self.text(root, "//n:GrpHdr/n:InitgPty/n:Id/n:OrgId/n:Othr/n:Id"),
            "DE1234567",
        )

    def test_payment_information(self):
        root = self.build(credit_transfer_payload())
        payment = self.nodes(root, "//n:PmtInf")[0]
        self.assertEqual(
            [etree.QName(child).localname for child in payment][:8],
            [
                "PmtInfId",
                "PmtMtd",
                "BtchBookg",
                "NbOfTxs",
                "CtrlSum",
                "PmtTpInf",
                "ReqdExctnDt",
                "Dbtr",
            ],
        )
        self.assertEqual(self.text(root, "//n:PmtInf/n:PmtInfId"), "PMT-1")
        self.assertEqual(self.text(root, "//n:PmtInf/n:PmtMtd"), "TRF")
        self.assertEqual(self.text(root, "//n:PmtInf/n:BtchBookg"), "true")
        self.assertEqual(self.text(root, "//n:PmtInf/n:NbOfTxs"), "2")
        self.assertEqual(self.text(root, "//n:PmtInf/n:CtrlSum"), "1244.56")
        self.assertEqual(self.text(root, "//n:PmtInf/n:PmtTpInf/n:SvcLvl/n:Cd"), "SEPA")
        self.assertEqual(self.text(root, "//n:PmtInf/n:ChrgBr"), "SLEV")
        self.assertEqual(
            self.text(root, "//n:PmtInf/n:DbtrAcct/n:Id/n:IBAN"), DEBTOR["iban"]
        )
        self.assertEqual(
            self.text(root, "//n:PmtInf/n:DbtrAgt/n:FinInstnId/n:BICFI"), DEBTOR["bic"]
        )
        self.assertEqual(self.text(root, "//n:PmtInf/n:Dbtr/n:PstlAdr/n:Ctry"), "DE")
        self.assertEqual(
            self.texts(root, "//n:PmtInf/n:Dbtr/n:PstlAdr/n:AdrLine"),
            DEBTOR["address_lines"],
        )

    def test_execution_date_is_wrapped_in_the_2019_version(self):
        root = self.build(credit_transfer_payload())
        self.assertEqual(self.text(root, "//n:PmtInf/n:ReqdExctnDt/n:Dt"), "2026-08-25")
        legacy = self.build(credit_transfer_payload(), version="pain.001.001.03")
        self.assertEqual(self.text(legacy, "//n:PmtInf/n:ReqdExctnDt"), "2026-08-25")
        self.assertEqual(
            self.text(legacy, "//n:PmtInf/n:DbtrAgt/n:FinInstnId/n:BIC"), DEBTOR["bic"]
        )

    def test_transactions(self):
        root = self.build(credit_transfer_payload())
        first, second = self.nodes(root, "//n:CdtTrfTxInf")
        self.assertEqual(
            [etree.QName(child).localname for child in first],
            ["PmtId", "Amt", "CdtrAgt", "Cdtr", "CdtrAcct", "RmtInf"],
        )
        self.assertEqual(self.text(first, ".//n:EndToEndId"), "INV-2026-0001")
        amount = self.nodes(first, ".//n:InstdAmt")[0]
        self.assertEqual(amount.text, "1234.56")
        self.assertEqual(amount.get("Ccy"), "EUR")
        self.assertEqual(self.text(first, ".//n:Cdtr/n:Nm"), CREDITOR["name"])
        self.assertEqual(
            self.text(first, ".//n:CdtrAcct/n:Id/n:IBAN"), CREDITOR["iban"]
        )
        self.assertEqual(
            self.text(first, ".//n:CdtrAgt/n:FinInstnId/n:BICFI"), CREDITOR["bic"]
        )
        self.assertEqual(self.text(first, ".//n:RmtInf/n:Ustrd"), "Rechnung 2026-0001")

        self.assertEqual(self.text(second, ".//n:EndToEndId"), "NOTPROVIDED")
        self.assertEqual(self.text(second, ".//n:InstdAmt"), "10.00")
        self.assertFalse(self.nodes(second, ".//n:CdtrAgt"))
        self.assertEqual(self.text(second, ".//n:Purp/n:Cd"), "GDDS")
        self.assertEqual(
            self.text(second, ".//n:RmtInf/n:Strd/n:CdtrRefInf/n:Ref"),
            "RF18539007547034",
        )
        self.assertEqual(
            self.text(second, ".//n:RmtInf/n:Strd/n:CdtrRefInf/n:Tp/n:CdOrPrtry/n:Cd"),
            "SCOR",
        )
        self.assertFalse(self.nodes(second, ".//n:RmtInf/n:Ustrd"))

    def test_totals_cover_every_payment_block(self):
        payload = credit_transfer_payload()
        payload["payments"].append(
            {
                "requested_date": "2026-08-26",
                "debtor": DEBTOR,
                "transactions": [{"amount": "0.44", "creditor": CREDITOR}],
            }
        )
        root = self.build(payload)
        self.assertEqual(self.text(root, "//n:GrpHdr/n:NbOfTxs"), "3")
        self.assertEqual(self.text(root, "//n:GrpHdr/n:CtrlSum"), "1245.00")
        self.assertEqual(self.texts(root, "//n:PmtInf/n:NbOfTxs"), ["2", "1"])
        self.assertEqual(self.texts(root, "//n:PmtInf/n:CtrlSum"), ["1244.56", "0.44"])

    def test_generated_ids_and_defaults(self):
        payload = credit_transfer_payload()
        del payload["message_id"]
        del payload["payments"][0]["payment_id"]
        del payload["payments"][0]["requested_date"]
        del payload["payments"][0]["batch_booking"]
        root = self.build(payload)
        self.assertTrue(self.text(root, "//n:GrpHdr/n:MsgId"))
        self.assertTrue(self.text(root, "//n:PmtInf/n:PmtInfId"))
        self.assertTrue(self.text(root, "//n:PmtInf/n:ReqdExctnDt/n:Dt"))
        self.assertFalse(self.nodes(root, "//n:BtchBookg"))

    def test_text_is_mapped_onto_the_sepa_character_set(self):
        payload = credit_transfer_payload()
        payload["payments"][0]["transactions"][0]["creditor"] = dict(
            CREDITOR, name="Müller & Söhne Großhandel " + "x" * 60
        )
        root = self.build(payload)
        name = self.text(root, "//n:CdtTrfTxInf[1]/n:Cdtr/n:Nm")
        self.assertTrue(name.startswith("Mueller + Soehne Grosshandel"))
        self.assertEqual(len(name), 70)

    def test_ultimate_parties(self):
        payload = credit_transfer_payload()
        payload["payments"][0]["ultimate_debtor"] = "Muster Holding GmbH"
        payload["payments"][0]["transactions"][0]["ultimate_creditor"] = {
            "name": "Factoring AG"
        }
        root = self.build(payload)
        self.assertEqual(
            self.text(root, "//n:PmtInf/n:UltmtDbtr/n:Nm"), "Muster Holding GmbH"
        )
        self.assertEqual(
            self.text(root, "//n:CdtTrfTxInf/n:UltmtCdtr/n:Nm"), "Factoring AG"
        )

    def test_rejected_payloads(self):
        cases = {
            "iban": (
                {"creditor": dict(CREDITOR, iban="DE89370400440532013001")},
                "IBAN",
            ),
            "bic": ({"creditor": dict(CREDITOR, bic="NOPE")}, "BIC"),
            "name": ({"creditor": dict(CREDITOR, name="")}, "name is required"),
            "amount": ({"amount": "0"}, "greater than zero"),
            "huge": ({"amount": "1000000000"}, "exceeds"),
        }
        for label, (override, expected) in cases.items():
            with self.subTest(label):
                payload = credit_transfer_payload()
                payload["payments"][0]["transactions"][0].update(override)
                ok, error = self.sepa._build_credit_transfer(payload)
                self.assertFalse(ok)
                self.assertIn(expected, error)

    def test_rejected_charge_bearer(self):
        payload = credit_transfer_payload()
        payload["payments"][0]["charge_bearer"] = "FREE"
        ok, error = self.sepa._build_credit_transfer(payload)
        self.assertFalse(ok)
        self.assertIn("charge_bearer must be one of", error)

    def test_rejected_structures(self):
        ok, error = self.sepa._build_credit_transfer({"payments": []})
        self.assertFalse(ok)
        self.assertIn("payment block", error)

        payload = credit_transfer_payload()
        payload["payments"][0]["transactions"] = []
        ok, error = self.sepa._build_credit_transfer(payload)
        self.assertFalse(ok)
        self.assertIn("no transactions", error)

        ok, error = self.sepa._build_credit_transfer(
            credit_transfer_payload(), version="pain.008.001.08"
        )
        self.assertFalse(ok)
        self.assertIn("supported", error)
