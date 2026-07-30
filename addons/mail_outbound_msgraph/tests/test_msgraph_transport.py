import base64
from email.message import EmailMessage
from unittest.mock import patch

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.tests.common import TransactionCase, tagged


def _build_message(html=None, text=None, attachments=()):
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>, carol@example.com"
    msg["Cc"] = "Dave <dave@example.com>"
    msg["Subject"] = "Hello"
    msg["Reply-To"] = "noreply@example.com"
    msg["Message-Id"] = "<unit-test@example.com>"
    msg["X-Odoo-Objects"] = "mail.template-42"
    msg["Received"] = "from foo by bar"  # non-X header, must be skipped
    if text is None and html is None:
        text = "plain"
    if text is not None and html is not None:
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
    elif html is not None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(text)
    for name, content, ctype in attachments:
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(
            content, maintype=maintype, subtype=subtype, filename=name
        )
    return msg


@tagged("post_install", "-at_install")
class TestMsGraphTransport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["ir.mail_server"].create(
            {
                "name": "Test Graph Server",
                "delivery_method": "msgraph",
                "ms_graph_default_sender": "odoo@example.com",
                "smtp_host": "unused",
            }
        )

    # ------------------------------------------------------------------
    # MIME → Graph payload
    # ------------------------------------------------------------------

    def test_payload_prefers_html_over_text(self):
        msg = _build_message(text="plain body", html="<p>hi</p>")
        payload = self.server._msgraph_build_payload(msg)
        self.assertEqual(payload["message"]["body"]["contentType"], "HTML")
        self.assertIn("<p>hi</p>", payload["message"]["body"]["content"])
        self.assertTrue(payload["saveToSentItems"])

    def test_payload_recipients_parse_names_and_lists(self):
        payload = self.server._msgraph_build_payload(_build_message())
        to = payload["message"]["toRecipients"]
        self.assertEqual(
            [r["emailAddress"]["address"] for r in to],
            ["bob@example.com", "carol@example.com"],
        )
        self.assertEqual(to[0]["emailAddress"]["name"], "Bob")
        cc = payload["message"]["ccRecipients"]
        self.assertEqual(cc[0]["emailAddress"]["address"], "dave@example.com")
        self.assertEqual(payload["message"]["bccRecipients"], [])

    def test_payload_replyto_is_top_level(self):
        payload = self.server._msgraph_build_payload(_build_message())
        self.assertEqual(
            payload["message"]["replyTo"][0]["emailAddress"]["address"],
            "noreply@example.com",
        )

    def test_payload_keeps_only_x_headers(self):
        headers = self.server._msgraph_build_payload(_build_message())[
            "message"
        ]["internetMessageHeaders"]
        names = [h["name"] for h in headers]
        self.assertIn("X-Odoo-Objects", names)
        self.assertNotIn("Received", names)
        self.assertNotIn("From", names)

    def test_payload_attachments_base64_encoded(self):
        msg = _build_message(
            attachments=[("invoice.pdf", b"%PDF-1.4 fake", "application/pdf")]
        )
        att = self.server._msgraph_build_payload(msg)["message"]["attachments"]
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0]["name"], "invoice.pdf")
        self.assertEqual(att[0]["contentType"], "application/pdf")
        self.assertEqual(att[0]["@odata.type"], "#microsoft.graph.fileAttachment")
        self.assertEqual(
            base64.b64decode(att[0]["contentBytes"]), b"%PDF-1.4 fake"
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def test_smtp_server_unaffected(self):
        smtp_srv = self.env["ir.mail_server"].create(
            {"name": "SMTP", "delivery_method": "smtp", "smtp_host": "mail"}
        )
        msg = _build_message()
        with patch.object(
            type(self.env["ir.mail_server"]).__mro__[1],
            "send_email",
            return_value="<smtp@example.com>",
        ) as super_send:
            result = smtp_srv.send_email(msg)
        super_send.assert_called_once()
        self.assertEqual(result, "<smtp@example.com>")

    def test_msgraph_send_uses_from_header_upn(self):
        msg = _build_message()
        with patch.object(
            type(self.env["ms.graph.service"]),
            "_graph_request",
            return_value=(True, {}),
        ) as graph:
            result = self.server.send_email(msg)
        self.assertEqual(result, "<unit-test@example.com>")
        graph.assert_called_once()
        method, path = graph.call_args.args[:2]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/users/alice@example.com/sendMail")

    def test_msgraph_fallback_sender_on_resource_not_found(self):
        msg = _build_message()
        responses = iter(
            [(False, "ResourceNotFound: mailbox missing"), (True, {})]
        )
        with patch.object(
            type(self.env["ms.graph.service"]),
            "_graph_request",
            side_effect=lambda *a, **kw: next(responses),
        ) as graph:
            self.server.send_email(msg)
        self.assertEqual(graph.call_count, 2)
        self.assertEqual(
            graph.call_args_list[1].args[1], "/users/odoo@example.com/sendMail"
        )

    def test_msgraph_send_uses_session_when_mail_server_id_missing(self):
        # mail.mail._send passes mail_server_id=mail.mail_server_id.id which
        # is False when the mail has no explicit server. The session sentinel
        # must carry the routing.
        msg = _build_message()
        session = self.env["ir.mail_server"].connect(mail_server_id=self.server.id)
        with patch.object(
            type(self.env["ms.graph.service"]),
            "_graph_request",
            return_value=(True, {}),
        ) as graph:
            result = self.env["ir.mail_server"].send_email(
                msg, mail_server_id=False, smtp_session=session
            )
        self.assertEqual(result, "<unit-test@example.com>")
        graph.assert_called_once()

    def test_msgraph_propagates_non_sender_errors(self):
        msg = _build_message()
        with patch.object(
            type(self.env["ms.graph.service"]),
            "_graph_request",
            return_value=(False, "TooManyRequests: throttled"),
        ), self.assertRaises(MailDeliveryException):
            self.server.send_email(msg)

