from lxml import etree
from odoo.tests.common import TransactionCase

CREDITOR_ID = "DE98ZZZ09999999999"

DEBTOR = {
    "name": "Muster GmbH",
    "iban": "DE89370400440532013000",
    "bic": "COBADEFFXXX",
    "country": "DE",
    "address_lines": ["Hauptstrasse 1", "10115 Berlin"],
}
CREDITOR = {
    "name": "Lieferant AG",
    "iban": "DE02120300000000202051",
    "bic": "BYLADEM1001",
}
OTHER_PARTY = {
    "name": "Kunde SARL",
    "iban": "FR1420041010050500013M02606",
}


def credit_transfer_payload(**overrides):
    payload = {
        "message_id": "MSG-CT-1",
        "creation_date_time": "2026-08-23T10:15:30Z",
        "initiating_party": {"name": "Muster GmbH", "identifier": "DE1234567"},
        "payments": [
            {
                "payment_id": "PMT-1",
                "requested_date": "2026-08-25",
                "batch_booking": True,
                "debtor": DEBTOR,
                "transactions": [
                    {
                        "end_to_end_id": "INV-2026-0001",
                        "amount": "1234.56",
                        "creditor": CREDITOR,
                        "remittance_info": "Rechnung 2026-0001",
                    },
                    {
                        "amount": 10,
                        "creditor": OTHER_PARTY,
                        "creditor_reference": "RF18539007547034",
                        "purpose": "GDDS",
                    },
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def direct_debit_payload(**overrides):
    payload = {
        "message_id": "MSG-DD-1",
        "creation_date_time": "2026-08-23T10:15:30Z",
        "initiating_party": {"name": "Lieferant AG"},
        "payments": [
            {
                "payment_id": "PMT-DD-1",
                "requested_date": "2026-09-01",
                "sequence_type": "RCUR",
                "creditor": CREDITOR,
                "creditor_scheme_id": CREDITOR_ID,
                "transactions": [
                    {
                        "end_to_end_id": "SUB-0001",
                        "amount": "49.90",
                        "debtor": DEBTOR,
                        "mandate": {"id": "MNDT-0001", "signature_date": "2024-02-01"},
                        "remittance_info": "Wartung August",
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


class SepaCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sepa = cls.env["sepa.xml"]

    def build(self, payload, document_type="credit_transfer", version=None):
        """Build a document, asserting it succeeded, and return its root element."""
        method = (
            self.sepa._build_credit_transfer
            if document_type == "credit_transfer"
            else self.sepa._build_direct_debit
        )
        ok, result = method(payload, version=version)
        self.assertTrue(ok, result)
        return etree.fromstring(result)

    def nodes(self, root, path):
        return root.xpath(path, namespaces={"n": root.nsmap[None]})

    def text(self, root, path):
        """Return the single text value at `path`, or "" when it is absent."""
        found = self.nodes(root, path)
        self.assertLessEqual(len(found), 1, f"{path} matched {len(found)} nodes")
        if not found:
            return ""
        node = found[0]
        return (node if isinstance(node, str) else node.text or "").strip()

    def texts(self, root, path):
        return [
            (node if isinstance(node, str) else node.text or "").strip()
            for node in self.nodes(root, path)
        ]
