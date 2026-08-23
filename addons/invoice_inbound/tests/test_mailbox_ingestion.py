from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from .common import CII_XML, build_pdf


def _message(message_id="AAA", has_attachments=True, internet_id="<a@example.com>"):
    return {
        "id": message_id,
        "internetMessageId": internet_id,
        "subject": "Rechnung",
        "hasAttachments": has_attachments,
        "from": {"emailAddress": {"address": "billing@vendor.example"}},
    }


def _attachment(attachment_id="ATT", name="invoice.pdf", content_type="application/pdf",
                inline=False):
    return {
        "id": attachment_id,
        "name": name,
        "contentType": content_type,
        "isInline": inline,
    }


@tagged("post_install", "-at_install")
class TestMailboxIngestion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Invoice = cls.env["invoice.inbound"]
        cls.mailbox_cls = type(cls.env["ms.graph.mailbox"])
        cls.pdf = build_pdf([("factur-x.xml", CII_XML)])
        cls.env["ir.config_parameter"].sudo().set_param(
            "invoice_inbound.mailbox", "rechnung@example.com"
        )

    def _patch_mailbox(self, **overrides):
        """Patch ms.graph.mailbox with sensible defaults, return the mocks."""
        defaults = {
            "_list_messages": (True, [_message()]),
            "_list_attachments": (True, [_attachment()]),
            "_fetch_attachment": (True, self.pdf),
            "_mark_read": (True, {}),
            "_move_message": (True, "NEWID"),
        }
        defaults.update(overrides)
        mocks = {}
        for name, return_value in defaults.items():
            patcher = patch.object(self.mailbox_cls, name, return_value=return_value)
            mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return mocks

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def test_no_mailbox_configured_touches_nothing(self):
        self.env["ir.config_parameter"].sudo().set_param("invoice_inbound.mailbox", "")
        mocks = self._patch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        mocks["_list_messages"].assert_not_called()

    def test_the_configured_folder_is_the_one_listed(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "invoice_inbound.folder", "AAMkFolderId"
        )
        mocks = self._patch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        self.assertEqual(
            mocks["_list_messages"].call_args.kwargs["folder"], "AAMkFolderId"
        )
        self.assertTrue(mocks["_list_messages"].call_args.kwargs["unread_only"])

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def test_an_attachment_becomes_an_invoice(self):
        self._patch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        invoice = self.Invoice.search([("email_message_id", "=", "<a@example.com>")])
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.source, "email")
        self.assertEqual(invoice.email_from, "billing@vendor.example")
        self.assertEqual(invoice.name, "invoice.pdf")
        # The embedded e-invoice is read as part of creation.
        self.assertEqual(invoice.invoice_number, "RE-2026-0042")

    def test_every_usable_attachment_becomes_its_own_invoice(self):
        mocks = self._patch_mailbox(
            _list_attachments=(
                True,
                [
                    _attachment("A1", "one.pdf"),
                    _attachment("A2", "two.xml", "application/xml"),
                ],
            )
        )
        mocks["_fetch_attachment"].side_effect = [(True, self.pdf), (True, CII_XML)]
        self.Invoice._cron_fetch_mailbox()
        self.assertEqual(
            self.Invoice.search_count([("email_message_id", "=", "<a@example.com>")]), 2
        )

    def test_inline_and_unrelated_attachments_are_ignored(self):
        self._patch_mailbox(
            _list_attachments=(
                True,
                [
                    _attachment("A1", "logo.png", "image/png"),
                    _attachment("A2", "signature.pdf", inline=True),
                ],
            )
        )
        self.Invoice._cron_fetch_mailbox()
        self.assertFalse(
            self.Invoice.search_count([("email_message_id", "=", "<a@example.com>")])
        )

    def test_a_message_without_attachments_is_filed_away_untouched(self):
        mocks = self._patch_mailbox(_list_messages=(True, [_message(has_attachments=False)]))
        self.Invoice._cron_fetch_mailbox()
        mocks["_list_attachments"].assert_not_called()
        mocks["_mark_read"].assert_called_once()

    def test_the_same_file_is_not_ingested_twice(self):
        self._patch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        self.assertEqual(
            self.Invoice.search_count([("email_message_id", "=", "<a@example.com>")]), 1
        )

    # ------------------------------------------------------------------
    # Filing the message away
    # ------------------------------------------------------------------

    def test_the_message_is_marked_read_and_moved_when_configured(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "invoice_inbound.processed_folder", "archive"
        )
        mocks = self._patch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        mocks["_mark_read"].assert_called_once()
        self.assertEqual(mocks["_move_message"].call_args.args[2], "archive")

    def test_without_a_processed_folder_the_message_is_only_marked_read(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "invoice_inbound.processed_folder", ""
        )
        mocks = self._patch_mailbox()
        self.Invoice._cron_fetch_mailbox()
        mocks["_mark_read"].assert_called_once()
        mocks["_move_message"].assert_not_called()

    def test_a_failed_mark_read_does_not_move_the_message(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "invoice_inbound.processed_folder", "archive"
        )
        mocks = self._patch_mailbox(_mark_read=(False, "ErrorItemNotFound"))
        self.Invoice._cron_fetch_mailbox()
        mocks["_move_message"].assert_not_called()
        # The invoice was created before the mailbox was touched, so nothing is lost.
        self.assertEqual(
            self.Invoice.search_count([("email_message_id", "=", "<a@example.com>")]), 1
        )

    # ------------------------------------------------------------------
    # Failures
    # ------------------------------------------------------------------

    def test_a_failed_listing_stops_the_run(self):
        mocks = self._patch_mailbox(_list_messages=(False, "Insufficient privileges"))
        self.Invoice._cron_fetch_mailbox()
        mocks["_list_attachments"].assert_not_called()

    def test_a_message_that_fails_stays_unread_and_creates_nothing(self):
        mocks = self._patch_mailbox(_fetch_attachment=(False, "ErrorItemNotFound"))
        self.Invoice._cron_fetch_mailbox()
        self.assertFalse(
            self.Invoice.search_count([("email_message_id", "=", "<a@example.com>")])
        )
        mocks["_mark_read"].assert_not_called()

    def test_one_broken_message_does_not_stop_the_others(self):
        messages = [_message("AAA", internet_id="<a@x>"), _message("BBB", internet_id="<b@x>")]
        mocks = self._patch_mailbox(_list_messages=(True, messages))
        mocks["_list_attachments"].side_effect = [
            (False, "ErrorItemNotFound"),
            (True, [_attachment()]),
        ]
        self.Invoice._cron_fetch_mailbox()
        self.assertFalse(self.Invoice.search_count([("email_message_id", "=", "<a@x>")]))
        self.assertEqual(self.Invoice.search_count([("email_message_id", "=", "<b@x>")]), 1)
