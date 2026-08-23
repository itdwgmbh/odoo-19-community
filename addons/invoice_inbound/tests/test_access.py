from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from .common import CII_XML, build_pdf


@tagged("post_install", "-at_install")
class TestInvoiceInboundAccess(TransactionCase):
    """The workflow gate has to hold server-side.

    `groups=` on a form button hides it and nothing more: the RPC behind it is
    still callable, and a plain `write` never reaches `_set_state`. These tests
    drive the model the way a client could, not the way the form does.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Invoice = cls.env["invoice.inbound"]
        cls.pdf = build_pdf([("factur-x.xml", CII_XML)])
        cls.user = cls.env["res.users"].create(
            {
                "name": "Inbox User",
                "login": "invoice-inbox-user",
                "group_ids": [
                    (4, cls.env.ref("invoice_inbound.group_invoice_inbound_user").id)
                ],
            }
        )
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Inbox Manager",
                "login": "invoice-inbox-manager",
                "group_ids": [
                    (4, cls.env.ref("invoice_inbound.group_invoice_inbound_manager").id)
                ],
            }
        )

    def _invoice(self, user=None):
        invoice = self.Invoice._create_from_file(self.pdf, "invoice.pdf")
        return invoice.with_user(user) if user else invoice

    # ------------------------------------------------------------------
    # What a user may do
    # ------------------------------------------------------------------

    def test_a_user_can_file_an_invoice(self):
        invoice = self.Invoice.with_user(self.user)._create_from_file(
            self.pdf, "invoice.pdf"
        )
        self.assertEqual(invoice.state, "incoming")
        self.assertEqual(invoice.invoice_number, "RE-2026-0042")

    def test_a_user_can_correct_the_extracted_data(self):
        invoice = self._invoice(self.user)
        invoice.write({"invoice_number": "corrected", "partner_name": "Someone"})
        self.assertEqual(invoice.invoice_number, "corrected")

    def test_a_user_can_edit_the_lines(self):
        invoice = self._invoice(self.user)
        invoice.line_ids[0].name = "Corrected line"
        self.assertEqual(invoice.line_ids[0].name, "Corrected line")

    def test_a_user_can_give_a_rejection_reason(self):
        invoice = self._invoice(self.user)
        invoice.rejection_reason = "Wrong address"
        self.assertEqual(invoice.rejection_reason, "Wrong address")

    # ------------------------------------------------------------------
    # What a user may not do
    # ------------------------------------------------------------------

    def test_a_user_cannot_write_the_state_directly(self):
        invoice = self._invoice(self.user)
        with self.assertRaises(AccessError):
            invoice.write({"state": "paid"})
        self.assertEqual(invoice.state, "incoming")

    def test_a_user_cannot_press_validate(self):
        invoice = self._invoice(self.user)
        with self.assertRaises(AccessError):
            invoice.action_validate()

    def test_a_user_cannot_press_mark_paid(self):
        # Paid is only reachable from validated, so a manager gets it there
        # first: otherwise the transition check fires before the access one.
        invoice = self._invoice()
        invoice.with_user(self.manager).action_validate()
        with self.assertRaises(AccessError):
            invoice.with_user(self.user).action_mark_paid()
        self.assertEqual(invoice.state, "validated")

    def test_a_user_cannot_press_reject(self):
        invoice = self._invoice(self.user)
        with self.assertRaises(AccessError):
            invoice.action_reject()

    def test_a_user_cannot_backdate_a_payment(self):
        invoice = self._invoice(self.user)
        with self.assertRaises(AccessError):
            invoice.write({"payment_date": "2026-01-01"})

    def test_a_user_cannot_archive_an_invoice_out_of_view(self):
        invoice = self._invoice(self.user)
        with self.assertRaises(AccessError):
            invoice.write({"active": False})

    def test_a_user_cannot_create_an_invoice_already_paid(self):
        import base64

        with self.assertRaises(AccessError):
            self.Invoice.with_user(self.user).create(
                {
                    "file": base64.b64encode(self.pdf),
                    "file_name": "invoice.pdf",
                    "state": "paid",
                }
            )

    def test_a_user_cannot_delete_an_invoice(self):
        invoice = self._invoice(self.user)
        with self.assertRaises(AccessError):
            invoice.unlink()

    # ------------------------------------------------------------------
    # What a manager may do
    # ------------------------------------------------------------------

    def test_a_manager_runs_the_whole_workflow(self):
        invoice = self._invoice(self.manager)
        invoice.action_validate()
        invoice.action_mark_paid()
        self.assertEqual(invoice.state, "paid")
        self.assertTrue(invoice.payment_date)

    def test_a_manager_can_archive_and_delete(self):
        invoice = self._invoice(self.manager)
        invoice.write({"active": False})
        self.assertFalse(invoice.active)
        invoice.unlink()

    def test_the_guard_does_not_stand_in_the_way_of_sudo(self):
        # Crons run as the superuser and must not be gated.
        invoice = self._invoice()
        invoice.sudo().write({"state": "validated"})
        self.assertEqual(invoice.state, "validated")

    # ------------------------------------------------------------------
    # Company isolation
    # ------------------------------------------------------------------

    def test_another_companys_invoice_is_invisible(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        invoice = self.Invoice.create(
            {
                "file": self._invoice().file,
                "file_name": "other.pdf",
                "company_id": other_company.id,
            }
        )
        self.assertFalse(invoice.with_user(self.user).search([("id", "=", invoice.id)]))

    def test_another_companys_lines_are_invisible(self):
        other_company = self.env["res.company"].create({"name": "Other Co 2"})
        invoice = self.Invoice.create(
            {
                "file": self._invoice().file,
                "file_name": "other.pdf",
                "company_id": other_company.id,
            }
        )
        self.assertTrue(invoice.line_ids)
        self.assertFalse(
            self.env["invoice.inbound.line"]
            .with_user(self.user)
            .search([("invoice_id", "=", invoice.id)])
        )
