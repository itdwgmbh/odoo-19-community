from datetime import UTC, date, datetime
from decimal import Decimal

from odoo.addons.sepa_xml_base.tools import sepa_format as fmt
from odoo.addons.sepa_xml_base.tools.sepa_format import SepaValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSepaFormat(TransactionCase):
    def test_sanitize_transliterates_and_strips(self):
        self.assertEqual(fmt.sanitize("Müller & Söhne GmbH"), "Mueller + Soehne GmbH")
        self.assertEqual(fmt.sanitize("Grüße"), "Gruesse")
        self.assertEqual(fmt.sanitize("Café Ångström"), "Cafe Aangstroem")
        self.assertEqual(fmt.sanitize("Rechnung #42*"), "Rechnung 42")
        self.assertEqual(fmt.sanitize("a\n\tb   c"), "a b c")
        self.assertEqual(fmt.sanitize(None), "")
        self.assertEqual(fmt.sanitize(42), "42")

    def test_sanitize_keeps_allowed_punctuation(self):
        self.assertEqual(fmt.sanitize("A/B-C?D:E(F)G.H,I'J+K"), "A/B-C?D:E(F)G.H,I'J+K")

    def test_sanitize_truncates(self):
        self.assertEqual(fmt.sanitize("abcdefgh", 3), "abc")
        self.assertEqual(fmt.sanitize("ab cdefgh", 3), "ab")

    def test_required_text_refuses_empty(self):
        self.assertEqual(fmt.required_text(" x ", "name"), "x")
        with self.assertRaises(SepaValidationError):
            fmt.required_text("***", "name")

    def test_normalize_iban(self):
        self.assertEqual(
            fmt.normalize_iban("de89 3704 0044 0532 0130 00"), "DE89370400440532013000"
        )
        for invalid in ("DE89370400440532013001", "DE8937040044", "not an iban", ""):
            with self.assertRaises(SepaValidationError):
                fmt.normalize_iban(invalid)

    def test_normalize_bic(self):
        self.assertEqual(fmt.normalize_bic("cobadeffxxx"), "COBADEFFXXX")
        self.assertEqual(fmt.normalize_bic("BYLADEM1001"), "BYLADEM1001")
        self.assertEqual(fmt.normalize_bic(None), "")
        with self.assertRaises(SepaValidationError):
            fmt.normalize_bic("COBADE")

    def test_normalize_creditor_identifier(self):
        self.assertEqual(
            fmt.normalize_creditor_identifier("DE98ZZZ09999999999"),
            "DE98ZZZ09999999999",
        )
        self.assertEqual(
            fmt.normalize_creditor_identifier("de98 zzz 09999999999"),
            "DE98ZZZ09999999999",
        )
        for invalid in ("DE31ZZZ00000000123", "DE99ZZZ09999999999", "DE98ZZZ", ""):
            with self.assertRaises(SepaValidationError):
                fmt.normalize_creditor_identifier(invalid)

    def test_format_amount(self):
        self.assertEqual(fmt.format_amount("10"), "10.00")
        self.assertEqual(fmt.format_amount(Decimal("1234.5")), "1234.50")
        self.assertEqual(fmt.format_amount(0.125), "0.13")
        for invalid in (0, "-1", "1000000000.00", "abc", None):
            with self.assertRaises(SepaValidationError):
                fmt.format_amount(invalid)

    def test_dates(self):
        self.assertEqual(fmt.format_date(date(2026, 8, 25)), "2026-08-25")
        self.assertEqual(fmt.format_date("2026-08-25"), "2026-08-25")
        self.assertEqual(
            fmt.format_date(datetime.fromisoformat("2026-08-25T13:00:00")),
            "2026-08-25",
        )
        with self.assertRaises(SepaValidationError):
            fmt.format_date("25.08.2026")

    def test_format_datetime_is_utc(self):
        moment = datetime(2026, 8, 23, 12, 15, 30, tzinfo=UTC)
        self.assertEqual(fmt.format_datetime(moment), "2026-08-23T12:15:30Z")
        self.assertEqual(
            fmt.format_datetime("2026-08-23T12:15:30Z"), "2026-08-23T12:15:30Z"
        )
        # Odoo stores naive UTC datetimes
        self.assertEqual(
            fmt.format_datetime(datetime.fromisoformat("2026-08-23T12:15:30")),
            "2026-08-23T12:15:30Z",
        )
        self.assertTrue(fmt.format_datetime().endswith("Z"))

    def test_generate_id_fits_the_schema(self):
        generated = fmt.generate_id("ODOO")
        self.assertTrue(generated.startswith("ODOO-"))
        self.assertLessEqual(len(generated), fmt.MAX_ID)
        self.assertNotEqual(generated, fmt.generate_id("ODOO"))
