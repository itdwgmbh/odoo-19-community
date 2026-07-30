import base64
import logging
from email.utils import getaddresses, parseaddr

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Graph error indicators that mean "this sender mailbox doesn't exist /
# can't be sent-as" — those trigger the default-sender fallback. Other
# failures (auth, throttling, payload validation) propagate as
# MailDeliveryException so Odoo retains the mail for retry.
_SENDER_NOT_FOUND_MARKERS = (
    "ResourceNotFound",
    "MailboxNotEnabled",
    "does not exist",
    "Object Not Found",
)


def _addresses(recipients):
    return [r["emailAddress"]["address"] for r in recipients if r.get("emailAddress", {}).get("address")]


class _MsGraphSession:
    """Sentinel handed back from connect() for msgraph servers.

    mail.mail.send() expects an smtp_session it can later .quit() — this
    no-op object lets that path work without opening an SMTP connection.
    The bound ``server`` lets send_email route through Graph even when the
    caller passes mail_server_id=False (mail.mail._send does exactly this
    when the mail record has no explicit server).
    """

    is_msgraph = True

    def __init__(self, server):
        self.server = server

    def quit(self):
        pass


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    # Not `required`: a NOT NULL column breaks raw SQL inserts into
    # ir_mail_server that omit it — notably Odoo's base/data/neutralize.sql
    # "disable emails" row, which would otherwise abort neutralization (and
    # every neutralized DB restore). NULL reads as falsy, so the routing below
    # treats it as plain SMTP; ORM-created servers still default to "smtp".
    delivery_method = fields.Selection(
        [("smtp", "SMTP"), ("msgraph", "Microsoft Graph")],
        default="smtp",
        help="Transport used to deliver mail. SMTP uses the SMTP fields "
        "below; Microsoft Graph posts to /users/{upn}/sendMail using the "
        "ms_graph_base credentials.",
    )
    ms_graph_default_sender = fields.Char(
        string="MS Graph Default Sender (UPN)",
        help="Mailbox UPN used when the From header doesn't resolve to a "
        "tenant mailbox (cron mails, noreply addresses, etc.).",
    )

    @api.constrains("delivery_method", "ms_graph_default_sender")
    def _check_msgraph_config(self):
        for srv in self:
            if srv.delivery_method == "msgraph" and not srv.ms_graph_default_sender:
                raise ValidationError(
                    _("Microsoft Graph delivery requires a default sender UPN.")
                )

    # ------------------------------------------------------------------
    # UI: connection test
    # ------------------------------------------------------------------

    def test_msgraph_connection(self):
        """Send a small test mail through Graph to the current user.

        Exercises token acquisition, sender permission, and the sendMail
        endpoint — the three things that go wrong in production. Falls back
        to the default sender if the user's address isn't a tenant mailbox,
        matching the runtime fallback.
        """
        self.ensure_one()
        if self.delivery_method != "msgraph":
            raise UserError(_("This server is not configured for Microsoft Graph."))

        recipient = self.env.user.email
        if not recipient:
            raise UserError(_("Your user has no email address — set one and retry."))

        sender = self.ms_graph_default_sender
        payload = {
            "message": {
                "subject": _("Odoo Microsoft Graph connection test"),
                "body": {
                    "contentType": "Text",
                    "content": _(
                        "This is a test mail sent from Odoo through Microsoft "
                        "Graph using mail server %s.",
                        self.name,
                    ),
                },
                "toRecipients": [{"emailAddress": {"address": recipient}}],
            },
            "saveToSentItems": False,
        }
        ok, body = self._msgraph_post_sendmail(sender, payload)
        if not ok:
            raise UserError(
                _("Microsoft Graph rejected the test mail: %s", body)
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _(
                    "Test mail sent from %(sender)s to %(recipient)s.",
                    sender=sender,
                    recipient=recipient,
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    # ------------------------------------------------------------------
    # Transport routing
    # ------------------------------------------------------------------

    def connect(self, *args, **kwargs):
        mail_server_id = kwargs.get("mail_server_id")
        if mail_server_id:
            server = self.sudo().browse(mail_server_id)
            if server.delivery_method == "msgraph":
                return _MsGraphSession(server)
        # No explicit server + no explicit host → Odoo resolves via
        # _find_mail_server (same lookup super() would do). Intercept here
        # so a Graph default server doesn't get handed to the SMTP path.
        elif not kwargs.get("host") and not (args and args[0]):
            smtp_from = kwargs.get("smtp_from")
            resolved, _from = self.sudo()._find_mail_server(smtp_from)
            if resolved and resolved.delivery_method == "msgraph":
                return _MsGraphSession(resolved)
        return super().connect(*args, **kwargs)

    def send_email(self, message, mail_server_id=None, smtp_session=None, **kwargs):
        # Trust the session first: mail.mail._send passes mail_server_id from
        # the mail record (often False), but the session was opened with the
        # resolved server from _split_by_mail_configuration.
        if isinstance(smtp_session, _MsGraphSession):
            return smtp_session.server._send_via_msgraph(message)
        server = None
        if mail_server_id:
            server = self.sudo().browse(mail_server_id)
        elif self and len(self) == 1:
            server = self
        if server and server.delivery_method == "msgraph":
            return server._send_via_msgraph(message)
        return super().send_email(
            message,
            mail_server_id=mail_server_id,
            smtp_session=smtp_session,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # MS Graph delivery
    # ------------------------------------------------------------------

    def _send_via_msgraph(self, message):
        """POST the message to Graph sendMail. Returns Message-Id on success.

        Raises MailDeliveryException on failure (matches super contract so
        mail.mail flips the record to 'exception' for retry).
        """
        from odoo.addons.base.models.ir_mail_server import MailDeliveryException

        self.ensure_one()
        message_id = message["Message-Id"] or ""
        payload = self._msgraph_build_payload(message)
        from_upn = self._msgraph_pick_sender(message)

        ok, body = self._msgraph_post_sendmail(from_upn, payload)
        if not ok and self._msgraph_should_fallback_sender(body):
            fallback = self.ms_graph_default_sender
            if fallback and fallback.lower() != from_upn.lower():
                _logger.info(
                    "ms_graph_send_fallback_sender",
                    extra={
                        "event": "ms_graph_send_fallback_sender",
                        "from_attempted": from_upn,
                        "from_fallback": fallback,
                        "message_id": message_id,
                        "reason": body,
                    },
                )
                ok, body = self._msgraph_post_sendmail(fallback, payload)
                from_upn = fallback

        if not ok:
            _logger.warning(
                "msgraph_send_failed",
                extra={
                    "event": "msgraph_send_failed",
                    "from": from_upn,
                    "message_id": message_id,
                    "error": body,
                },
            )
            raise MailDeliveryException(
                _("Mail Delivery Failed"),
                _("Microsoft Graph rejected the message: %s", body),
            )

        graph_msg = payload["message"]
        _logger.info(
            "msgraph_mail_sent",
            extra={
                "event": "msgraph_mail_sent",
                "from": from_upn,
                "subject": graph_msg.get("subject"),
                "to": _addresses(graph_msg.get("toRecipients", [])),
                "cc": _addresses(graph_msg.get("ccRecipients", [])),
                "bcc": _addresses(graph_msg.get("bccRecipients", [])),
                "has_attachments": bool(graph_msg.get("attachments")),
                "message_id": message_id,
            },
        )
        return message_id

    def _msgraph_post_sendmail(self, from_upn, payload):
        return self.env["ms.graph.service"]._graph_request(
            "POST", f"/users/{from_upn}/sendMail", json_data=payload
        )

    def _msgraph_should_fallback_sender(self, error_message):
        if not error_message or not isinstance(error_message, str):
            return False
        return any(m in error_message for m in _SENDER_NOT_FOUND_MARKERS)

    def _msgraph_pick_sender(self, message):
        _, addr = parseaddr(message.get("From") or "")
        return addr or self.ms_graph_default_sender or ""

    # ------------------------------------------------------------------
    # MIME → Graph payload
    # ------------------------------------------------------------------

    def _msgraph_build_payload(self, message):
        graph_msg = {
            "subject": message.get("Subject") or "",
            "body": self._msgraph_extract_body(message),
            "toRecipients": self._msgraph_addr_list(message.get_all("To") or []),
            "ccRecipients": self._msgraph_addr_list(message.get_all("Cc") or []),
            "bccRecipients": self._msgraph_addr_list(message.get_all("Bcc") or []),
        }
        reply_to = self._msgraph_addr_list(message.get_all("Reply-To") or [])
        if reply_to:
            graph_msg["replyTo"] = reply_to
        headers = self._msgraph_custom_headers(message)
        if headers:
            graph_msg["internetMessageHeaders"] = headers
        attachments = self._msgraph_attachments(message)
        if attachments:
            graph_msg["attachments"] = attachments
        return {"message": graph_msg, "saveToSentItems": True}

    def _msgraph_addr_list(self, header_values):
        recipients = []
        for name, addr in getaddresses(header_values):
            if not addr:
                continue
            entry = {"emailAddress": {"address": addr}}
            if name:
                entry["emailAddress"]["name"] = name
            recipients.append(entry)
        return recipients

    def _msgraph_extract_body(self, message):
        html_part = None
        text_part = None
        for part in message.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            if ctype == "text/html" and html_part is None:
                html_part = part
            elif ctype == "text/plain" and text_part is None:
                text_part = part
        chosen = html_part or text_part
        if chosen is None:
            return {"contentType": "Text", "content": ""}
        content = chosen.get_payload(decode=True) or b""
        charset = chosen.get_content_charset() or "utf-8"
        try:
            content = content.decode(charset, errors="replace")
        except LookupError:
            content = content.decode("utf-8", errors="replace")
        return {
            "contentType": "HTML" if chosen is html_part else "Text",
            "content": content,
        }

    def _msgraph_custom_headers(self, message):
        # Graph rejects internetMessageHeaders whose name doesn't start with x-.
        # Standard envelope/threading headers (From, To, Cc, Bcc, Reply-To,
        # Subject, Message-Id, Date, MIME-Version, Content-*) belong on the
        # Graph message object or are set by the service itself.
        out = []
        for name, value in message.items():
            if name.lower().startswith("x-"):
                out.append({"name": name, "value": str(value)})
        return out

    def _msgraph_attachments(self, message):
        attachments = []
        for part in message.iter_attachments():
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            attachments.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": part.get_filename() or "attachment",
                    "contentType": part.get_content_type(),
                    "contentBytes": base64.b64encode(payload).decode("ascii"),
                }
            )
        return attachments
