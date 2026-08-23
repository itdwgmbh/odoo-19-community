from lxml import etree
from odoo.tests.common import tagged

from .common import CREDITOR, CREDITOR_ID, DEBTOR, SepaCase, direct_debit_payload


@tagged("post_install", "-at_install")
class TestSepaDirectDebit(SepaCase):
    def build_dd(self, payload, version=None):
        return self.build(payload, "direct_debit", version)

    def test_document_shape(self):
        root = self.build_dd(direct_debit_payload())
        self.assertEqual(
            root.nsmap[None], "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
        )
        self.assertEqual(len(self.nodes(root, "/n:Document/n:CstmrDrctDbtInitn")), 1)
        self.assertEqual(self.text(root, "//n:GrpHdr/n:NbOfTxs"), "1")
        self.assertEqual(self.text(root, "//n:GrpHdr/n:CtrlSum"), "49.90")

    def test_payment_information(self):
        root = self.build_dd(direct_debit_payload())
        payment = self.nodes(root, "//n:PmtInf")[0]
        self.assertEqual(
            [etree.QName(child).localname for child in payment],
            [
                "PmtInfId",
                "PmtMtd",
                "NbOfTxs",
                "CtrlSum",
                "PmtTpInf",
                "ReqdColltnDt",
                "Cdtr",
                "CdtrAcct",
                "CdtrAgt",
                "ChrgBr",
                "CdtrSchmeId",
                "DrctDbtTxInf",
            ],
        )
        self.assertEqual(self.text(root, "//n:PmtInf/n:PmtMtd"), "DD")
        self.assertEqual(self.text(root, "//n:PmtInf/n:ReqdColltnDt"), "2026-09-01")
        self.assertEqual(self.text(root, "//n:PmtInf/n:PmtTpInf/n:SvcLvl/n:Cd"), "SEPA")
        self.assertEqual(
            self.text(root, "//n:PmtInf/n:PmtTpInf/n:LclInstrm/n:Cd"), "CORE"
        )
        self.assertEqual(self.text(root, "//n:PmtInf/n:PmtTpInf/n:SeqTp"), "RCUR")
        self.assertEqual(
            self.text(root, "//n:PmtInf/n:CdtrAcct/n:Id/n:IBAN"), CREDITOR["iban"]
        )
        self.assertEqual(
            self.text(root, "//n:PmtInf/n:CdtrAgt/n:FinInstnId/n:BICFI"),
            CREDITOR["bic"],
        )
        self.assertEqual(
            self.text(root, "//n:CdtrSchmeId/n:Id/n:PrvtId/n:Othr/n:Id"), CREDITOR_ID
        )
        self.assertEqual(
            self.text(root, "//n:CdtrSchmeId/n:Id/n:PrvtId/n:Othr/n:SchmeNm/n:Prtry"),
            "SEPA",
        )

    def test_transaction(self):
        root = self.build_dd(direct_debit_payload())
        transaction = self.nodes(root, "//n:DrctDbtTxInf")[0]
        self.assertEqual(
            [etree.QName(child).localname for child in transaction],
            ["PmtId", "InstdAmt", "DrctDbtTx", "DbtrAgt", "Dbtr", "DbtrAcct", "RmtInf"],
        )
        amount = self.nodes(transaction, "./n:InstdAmt")[0]
        self.assertEqual(amount.text, "49.90")
        self.assertEqual(amount.get("Ccy"), "EUR")
        self.assertEqual(self.text(transaction, ".//n:EndToEndId"), "SUB-0001")
        self.assertEqual(self.text(transaction, ".//n:Dbtr/n:Nm"), DEBTOR["name"])
        self.assertEqual(
            self.text(transaction, ".//n:DbtrAcct/n:Id/n:IBAN"), DEBTOR["iban"]
        )
        self.assertEqual(
            self.text(transaction, ".//n:DbtrAgt/n:FinInstnId/n:BICFI"), DEBTOR["bic"]
        )
        self.assertEqual(
            self.text(transaction, ".//n:MndtRltdInf/n:MndtId"), "MNDT-0001"
        )
        self.assertEqual(
            self.text(transaction, ".//n:MndtRltdInf/n:DtOfSgntr"), "2024-02-01"
        )
        self.assertEqual(
            self.text(transaction, ".//n:MndtRltdInf/n:AmdmntInd"), "false"
        )

    def test_missing_bic_falls_back_to_the_iban_only_placeholder(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["debtor"] = {
            "name": DEBTOR["name"],
            "iban": DEBTOR["iban"],
        }
        root = self.build_dd(payload)
        self.assertEqual(
            self.text(root, "//n:DbtrAgt/n:FinInstnId/n:Othr/n:Id"), "NOTPROVIDED"
        )

    def test_mandate_amendment(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["mandate"]["amendment"] = {
            "original_mandate_id": "OLD-0001",
            "original_creditor_scheme_id": CREDITOR_ID,
            "original_creditor_name": "Lieferant KG",
        }
        root = self.build_dd(payload)
        self.assertEqual(self.text(root, "//n:MndtRltdInf/n:AmdmntInd"), "true")
        details = self.nodes(root, "//n:AmdmntInfDtls")[0]
        self.assertEqual(
            [etree.QName(child).localname for child in details],
            ["OrgnlMndtId", "OrgnlCdtrSchmeId"],
        )
        self.assertEqual(self.text(details, "./n:OrgnlMndtId"), "OLD-0001")
        self.assertEqual(
            self.text(details, ".//n:OrgnlCdtrSchmeId/n:Nm"), "Lieferant KG"
        )
        self.assertEqual(
            self.text(details, ".//n:OrgnlCdtrSchmeId/n:Id/n:PrvtId/n:Othr/n:Id"),
            CREDITOR_ID,
        )

    def test_new_debtor_account_flag_follows_the_version(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["mandate"]["amendment"] = {
            "same_mandate_new_debtor_account": True
        }
        root = self.build_dd(payload)
        self.assertEqual(
            self.text(root, "//n:AmdmntInfDtls/n:OrgnlDbtrAcct/n:Id/n:Othr/n:Id"),
            "SMNDA",
        )
        legacy = self.build_dd(payload, version="pain.008.001.02")
        self.assertEqual(
            self.text(
                legacy, "//n:AmdmntInfDtls/n:OrgnlDbtrAgt/n:FinInstnId/n:Othr/n:Id"
            ),
            "SMNDA",
        )
        self.assertEqual(
            self.text(legacy, "//n:PmtInf/n:CdtrAgt/n:FinInstnId/n:BIC"),
            CREDITOR["bic"],
        )

    def test_original_debtor_account(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["mandate"]["amendment"] = {
            "original_debtor_iban": "DE02100500000054540402"
        }
        root = self.build_dd(payload)
        self.assertEqual(
            self.text(root, "//n:AmdmntInfDtls/n:OrgnlDbtrAcct/n:Id/n:IBAN"),
            "DE02100500000054540402",
        )

    def test_b2b_and_first_collection(self):
        payload = direct_debit_payload()
        payload["payments"][0].update(
            {"local_instrument": "B2B", "sequence_type": "FRST"}
        )
        root = self.build_dd(payload)
        self.assertEqual(self.text(root, "//n:PmtTpInf/n:LclInstrm/n:Cd"), "B2B")
        self.assertEqual(self.text(root, "//n:PmtTpInf/n:SeqTp"), "FRST")

    def test_rejected_payloads(self):
        cases = {
            "sequence": ({"sequence_type": "MONTHLY"}, "sequence_type must be"),
            "scheme": ({"creditor_scheme_id": "DE31ZZZ00000000123"}, "check digits"),
            "no_scheme": ({"creditor_scheme_id": None}, "creditor identifier"),
        }
        for label, (override, expected) in cases.items():
            with self.subTest(label):
                payload = direct_debit_payload()
                payload["payments"][0].update(override)
                ok, error = self.sepa._build_direct_debit(payload)
                self.assertFalse(ok)
                self.assertIn(expected, error)

    def test_mandate_is_required(self):
        for mandate, expected in (
            ({}, "mandate id is required"),
            ({"id": "M-1"}, "signature_date is required"),
            ({"id": "M-1", "signature_date": "01.02.2024"}, "is not a date"),
        ):
            with self.subTest(str(mandate)):
                payload = direct_debit_payload()
                payload["payments"][0]["transactions"][0]["mandate"] = mandate
                ok, error = self.sepa._build_direct_debit(payload)
                self.assertFalse(ok)
                self.assertIn(expected, error)

    def test_conflicting_amendment(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["mandate"]["amendment"] = {
            "original_debtor_iban": DEBTOR["iban"],
            "same_mandate_new_debtor_account": True,
        }
        ok, error = self.sepa._build_direct_debit(payload)
        self.assertFalse(ok)
        self.assertIn("same_mandate_new_debtor_account", error)

    def test_empty_amendment_is_rejected(self):
        payload = direct_debit_payload()
        payload["payments"][0]["transactions"][0]["mandate"]["amendment"] = {
            "unknown_key": "x"
        }
        ok, error = self.sepa._build_direct_debit(payload)
        self.assertFalse(ok)
        self.assertIn("names nothing that changed", error)
