import base64
import hashlib
import logging

from odoo import Command, _, api, fields, models, modules
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# Document Intelligence model used when a file carries no e-invoice XML.
DI_INVOICE_MODEL = "prebuilt-invoice"

# Mail attachments worth turning into an invoice: everything else on an
# incoming message (signatures, logos, read receipts) is ignored.
INVOICE_MIMETYPES = ("application/pdf", "application/xml", "text/xml")
INVOICE_EXTENSIONS = (".pdf", ".xml")

# prebuilt-invoice field names, mapped onto this model. Fields whose DI type is
# `currency` also carry the currency code and are unpacked separately.
DI_FIELD_MAP = {
    "VendorName": "partner_name",
    "VendorTaxId": "partner_vat",
    "InvoiceId": "invoice_number",
    "InvoiceDate": "invoice_date",
    "DueDate": "date_due",
    "PurchaseOrder": "purchase_order",
    "PaymentTerm": "payment_terms",
    "SubTotal": "amount_untaxed",
    "TotalTax": "amount_tax",
    "InvoiceTotal": "amount_total",
}
DI_CURRENCY_FIELDS = ("SubTotal", "TotalTax", "InvoiceTotal")
DI_DATE_FIELDS = ("InvoiceDate", "DueDate")
DI_AMOUNT_FIELDS = ("amount_untaxed", "amount_tax", "amount_total")

# prebuilt-invoice Items.* sub-fields, mapped onto invoice.inbound.line.
DI_LINE_MAP = {
    "Description": "name",
    "ProductCode": "product_code",
    "Quantity": "quantity",
    "Unit": "uom",
    "UnitPrice": "price_unit",
    "Amount": "amount",
    "TaxRate": "tax_rate",
}
DI_LINE_CURRENCY_FIELDS = ("UnitPrice", "Amount")
DI_LINE_NUMBER_FIELDS = ("Quantity",)

# Writing any of these moves an invoice through the approval workflow, so they
# are manager-only. `groups=` on a button hides it and nothing more.
MANAGER_ONLY_FIELDS = frozenset(("state", "active", "payment_date"))

# Target state -> states it may be reached from.
STATE_TRANSITIONS = {
    "incoming": ("validated", "rejected", "paid"),
    "validated": ("incoming", "rejected"),
    "rejected": ("incoming", "validated"),
    "paid": ("validated",),
}


class InvoiceInbound(models.Model):
    """One incoming supplier invoice, from arrival to payment.

    The record is the document: it holds the file, the header fields read out
    of it, and the state it has reached. Nothing here posts to Accounting —
    the books are kept elsewhere.
    """

    _name = "invoice.inbound"
    _description = "Inbound Invoice"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "invoice_date desc, id desc"

    name = fields.Char(
        string="Document", tracking=True,
        help="Label this invoice is filed under. Taken from the file name on "
             "arrival and never overwritten by extraction.",
    )
    state = fields.Selection(
        [
            ("incoming", "Incoming"),
            ("validated", "Validated"),
            ("rejected", "Rejected"),
            ("paid", "Paid"),
        ],
        default="incoming",
        required=True,
        index=True,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, default=lambda self: self.env.company
    )
    user_id = fields.Many2one(
        "res.users", string="Responsible", tracking=True,
        default=lambda self: self.env.user,
    )

    # ==== Vendor ====
    partner_id = fields.Many2one("res.partner", string="Vendor", tracking=True)
    partner_name = fields.Char(string="Vendor Name", tracking=True)
    partner_vat = fields.Char(string="Vendor VAT")

    # ==== Document ====
    document_type = fields.Selection(
        [("invoice", "Invoice"), ("credit_note", "Credit Note")],
        default="invoice",
        required=True,
        index=True,
        tracking=True,
        help="Read from the document. A credit note owes money back, so its "
             "total counts negatively in list sums.",
    )
    invoice_number = fields.Char(string="Invoice Number", tracking=True)
    invoice_date = fields.Date(string="Invoice Date", tracking=True)
    date_due = fields.Date(string="Due Date", tracking=True)
    purchase_order = fields.Char(string="Order Reference")
    payment_terms = fields.Char(string="Payment Terms")
    payment_reference = fields.Char(string="Payment Reference")
    iban = fields.Char(string="Vendor IBAN")

    # ==== Amounts ====
    currency_id = fields.Many2one(
        "res.currency", string="Currency", default=lambda self: self.env.company.currency_id
    )
    amount_untaxed = fields.Monetary(string="Untaxed Amount", tracking=True)
    amount_tax = fields.Monetary(string="Taxes")
    amount_total = fields.Monetary(
        string="Total", tracking=True,
        help="As printed on the document, and positive on a credit note too.",
    )
    amount_total_signed = fields.Monetary(
        string="Signed Total", compute="_compute_amount_total_signed", store=True,
        help="The total with a credit note's sign flipped, so a mixed list "
             "adds up to what is actually owed.",
    )

    # ==== Lines ====
    line_ids = fields.One2many(
        "invoice.inbound.line", "invoice_id", string="Lines", copy=True
    )
    lines_amount = fields.Monetary(
        string="Lines Total", compute="_compute_lines_amount",
        help="Sum of the line subtotals.",
    )
    lines_match = fields.Boolean(
        string="Lines Match", compute="_compute_lines_amount",
        help="Whether the line subtotals add up to the untaxed amount. A "
             "document-level discount or charge makes them differ legitimately.",
    )

    # ==== File ====
    file = fields.Binary(string="Invoice File", attachment=True, required=True)
    file_name = fields.Char(string="File Name")
    file_checksum = fields.Char(
        string="Checksum", index=True, copy=False, readonly=True,
        help="SHA-256 of the file, used to recognise a document already ingested.",
    )

    # ==== Origin ====
    source = fields.Selection(
        [("manual", "Manual Upload"), ("email", "Mailbox")],
        default="manual",
        required=True,
        readonly=True,
    )
    email_from = fields.Char(string="Sender", readonly=True)
    email_message_id = fields.Char(
        string="Source Message-Id", index=True, copy=False, readonly=True
    )

    # ==== Extraction ====
    extraction_state = fields.Selection(
        [("pending", "Pending"), ("done", "Done"), ("failed", "Failed")],
        default="pending",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    extraction_method = fields.Selection(
        [("einvoice", "E-Invoice"), ("ocr", "Azure OCR")],
        readonly=True,
        copy=False,
    )
    extraction_confidence = fields.Float(
        string="Confidence", digits=(3, 2), readonly=True, copy=False,
        help="Model confidence for an OCR extraction. Always 1 for an e-invoice, "
             "whose fields are read rather than recognised.",
    )
    extraction_error = fields.Char(readonly=True, copy=False)
    extraction_payload = fields.Json(
        string="Extracted Fields", readonly=True, copy=False,
        help="Per-field values and confidences as returned by the extractor.",
    )

    # ==== Workflow ====
    payment_date = fields.Date(readonly=True, copy=False, tracking=True)
    rejection_reason = fields.Text(tracking=True)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("amount_total", "document_type")
    def _compute_amount_total_signed(self):
        for invoice in self:
            sign = -1 if invoice.document_type == "credit_note" else 1
            invoice.amount_total_signed = sign * invoice.amount_total

    @api.depends("line_ids.amount", "amount_untaxed")
    def _compute_lines_amount(self):
        for invoice in self:
            invoice.lines_amount = sum(invoice.line_ids.mapped("amount"))
            rounding = invoice.currency_id.rounding or 0.01
            invoice.lines_match = bool(invoice.line_ids) and (
                abs(invoice.lines_amount - invoice.amount_untaxed) < rounding
            )

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def _check_manager_fields(self, vals):
        """Gate the workflow fields on the manager group, server-side.

        `groups=` on a button only hides it in the form: the RPC behind it stays
        callable, and a plain `write` skips `_set_state` altogether. Without
        this an Invoice Inbox user could mark a supplier invoice paid without it
        ever having been validated, or archive it out of every view.
        """
        if self.env.su:
            return
        restricted = MANAGER_ONLY_FIELDS.intersection(vals)
        if restricted and not self.env.user.has_group(
            "invoice_inbound.group_invoice_inbound_manager"
        ):
            raise AccessError(
                _(
                    "Only an Invoice Inbox manager can change: %(fields)s",
                    fields=", ".join(sorted(restricted)),
                )
            )

    def write(self, vals):
        self._check_manager_fields(vals)
        return super().write(vals)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_manager_fields(vals)
            if vals.get("file") and not vals.get("file_checksum"):
                vals["file_checksum"] = self._checksum(base64.b64decode(vals["file"]))
            # Not a required field: an upload has a file long before it has a
            # name, and blocking the save on one would be in the way.
            if not vals.get("name"):
                vals["name"] = vals.get("file_name") or _("Invoice")
        records = super().create(vals_list)
        # Reading an embedded e-invoice is local and takes milliseconds, so it
        # runs now and the upload comes back with its fields filled in. Files
        # without one stay pending for the OCR cron, which does hit the network.
        for record in records:
            record._extract_einvoice()
        return records

    @api.model
    def _checksum(self, content):
        return hashlib.sha256(content).hexdigest()

    @api.model
    def _create_from_file(self, content, file_name, values=None):
        """Create one invoice from raw file bytes."""
        return self.create(
            {
                "file": base64.b64encode(content),
                "file_name": file_name,
                "file_checksum": self._checksum(content),
                **(values or {}),
            }
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _set_state(self, target, values=None):
        allowed = STATE_TRANSITIONS[target]
        blocked = self.filtered(lambda record: record.state not in allowed)
        if blocked:
            raise UserError(
                _(
                    "%(document)s is %(state)s and cannot be moved to %(target)s.",
                    document=blocked[0].display_name,
                    state=dict(self._fields["state"].selection)[blocked[0].state],
                    target=dict(self._fields["state"].selection)[target],
                )
            )
        self.write({"state": target, **(values or {})})

    def action_validate(self):
        self._set_state("validated", {"rejection_reason": False})

    def action_reject(self):
        self._set_state("rejected")

    def action_mark_paid(self):
        self._set_state("paid", {"payment_date": fields.Date.context_today(self)})

    def action_reset_to_incoming(self):
        self._set_state(
            "incoming", {"payment_date": False, "rejection_reason": False}
        )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def action_extract(self):
        """Re-run extraction, overwriting the fields it can fill."""
        for record in self:
            ok, message = record._extract(overwrite=True)
            if not ok and len(self) == 1:
                raise UserError(message)
        return True

    def _content(self):
        """The invoice file as raw bytes.

        `bin_size` must be off: with it, reading a Binary gives the human
        readable size instead of the payload, and the web client sets it on
        every form read — so a button pressed on the form would otherwise hand
        the extractor the string "6.23 Kb".
        """
        self.ensure_one()
        return base64.b64decode(self.with_context(bin_size=False).file or b"")

    def _extract(self, overwrite=False):
        """Fill the header fields from the file. Returns (ok, message)."""
        self.ensure_one()
        if self._extract_einvoice(overwrite=overwrite):
            return True, _("Read from the embedded e-invoice.")
        return self._extract_ocr(overwrite=overwrite)

    def _extract_einvoice(self, overwrite=False):
        """Read a ZUGFeRD / Factur-X / XRechnung document. True when it was one.

        Never raises: a malformed file must not stop a record being created.
        """
        self.ensure_one()
        content = self._content()
        if not content:
            return False
        try:
            values = self.env["invoice.einvoice.parser"]._parse(content)
        except Exception as e:
            _logger.exception(
                "invoice_inbound_einvoice_failed",
                extra={
                    "event": "invoice_inbound_einvoice_failed",
                    "invoice_id": self.id,
                    "error": str(e),
                },
            )
            return False
        if values is None:
            return False
        # A recognisable root with nothing readable inside it is treated as no
        # e-invoice at all, so the file still gets its chance at OCR.
        if not any(value for name, value in values.items() if name != "document_type"):
            return False
        self._apply_values(values, overwrite=overwrite)
        self.write(
            {
                "extraction_state": "done",
                "extraction_method": "einvoice",
                "extraction_confidence": 1.0,
                "extraction_error": False,
                "extraction_payload": {
                    name: {"value": self._json_safe(value), "confidence": 1.0}
                    for name, value in values.items()
                    if name != "lines"
                },
            }
        )
        return True

    def _extract_ocr(self, overwrite=False):
        """Send the file to Azure Document Intelligence. Returns (ok, message)."""
        self.ensure_one()
        content = self._content()
        if not content:
            return self._extraction_failed(_("The invoice has no file to analyse."))

        di = self.env["azure.document.intelligence"]
        ok, result = di._analyze(DI_INVOICE_MODEL, content)
        if not ok:
            return self._extraction_failed(result)

        di_fields = di._document_fields(result)
        if not di_fields:
            return self._extraction_failed(
                _("Document Intelligence recognised no invoice in this file.")
            )

        values, confidences = self._values_from_di(di_fields)
        self._apply_values(values, overwrite=overwrite)
        self.write(
            {
                "extraction_state": "done",
                "extraction_method": "ocr",
                "extraction_confidence": di._document_confidence(result) or 0.0,
                "extraction_error": False,
                "extraction_payload": {
                    name: {
                        "value": self._json_safe(value),
                        "confidence": confidences.get(name),
                    }
                    for name, value in values.items()
                    if name != "lines"
                },
            }
        )
        return True, _("Read by Azure Document Intelligence.")

    def _extraction_failed(self, message):
        self.write({"extraction_state": "failed", "extraction_error": message})
        _logger.warning(
            "invoice_inbound_extraction_failed",
            extra={
                "event": "invoice_inbound_extraction_failed",
                "invoice_id": self.id,
                "error": message,
            },
        )
        return False, message

    def _values_from_di(self, di_fields):
        """Translate prebuilt-invoice fields into this model's values.

        Returns (values, confidences), both keyed on this model's field names
        so an OCR payload reads the same way as an e-invoice one.
        """
        values = {}
        confidences = {}
        for di_name, field_name in DI_FIELD_MAP.items():
            entry = di_fields.get(di_name)
            if not entry or entry.get("value") in (None, ""):
                continue
            value = entry["value"]
            if di_name in DI_CURRENCY_FIELDS:
                # A currency field carries the amount and the code together;
                # the code is the same on every one of them.
                if not isinstance(value, dict) or value.get("amount") is None:
                    continue
                values[field_name] = value["amount"]
                if value.get("currencyCode"):
                    values.setdefault("currency_code", value["currencyCode"])
            elif di_name in DI_DATE_FIELDS:
                value = fields.Date.to_date(value)
                if value is None:
                    continue
                values[field_name] = value
            else:
                values[field_name] = value
            confidences[field_name] = entry.get("confidence")

        # IBAN sits inside the PaymentDetails array, one entry per payment way.
        for detail in (di_fields.get("PaymentDetails") or {}).get("value") or []:
            if isinstance(detail, dict) and detail.get("IBAN"):
                values["iban"] = detail["IBAN"]
                confidences["iban"] = (di_fields["PaymentDetails"] or {}).get(
                    "confidence"
                )
                break

        # prebuilt-invoice has no document-type field, so a credit note shows
        # up only as a negative total. Amounts are stored the way an e-invoice
        # states them — positive, with document_type carrying the sign.
        if values.get("amount_total", 0) < 0:
            values["document_type"] = "credit_note"
            for name in DI_AMOUNT_FIELDS:
                if name in values:
                    values[name] = abs(values[name])

        lines = self._lines_from_di(di_fields)
        if lines:
            values["lines"] = lines
        return values, confidences

    def _lines_from_di(self, di_fields):
        """Line items out of the prebuilt-invoice Items array.

        Document Intelligence reports confidence for the array as a whole, not
        per line, so every line carries the same figure.
        """
        items = di_fields.get("Items") or {}
        confidence = items.get("confidence")
        lines = []
        for sequence, item in enumerate(items.get("value") or [], start=1):
            if not isinstance(item, dict):
                continue
            line = {"sequence": sequence * 10, "confidence": confidence}
            for di_name, field_name in DI_LINE_MAP.items():
                value = item.get(di_name)
                if value in (None, ""):
                    continue
                if di_name in DI_LINE_CURRENCY_FIELDS:
                    if isinstance(value, dict) and value.get("amount") is not None:
                        line[field_name] = value["amount"]
                elif di_name == "TaxRate":
                    rate = self._percentage(value)
                    if rate is not None:
                        line[field_name] = rate
                elif di_name in DI_LINE_NUMBER_FIELDS:
                    if isinstance(value, (int, float)):
                        line[field_name] = value
                else:
                    line[field_name] = value
            if len(line) > 2:
                lines.append(line)
        return lines

    @api.model
    def _percentage(self, value):
        """A float out of a rate the model reports as text, e.g. "19 %"."""
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).replace("%", "").replace(",", ".").strip())
        except ValueError:
            return None

    def _apply_values(self, values, overwrite=False):
        """Write extracted values, then try to match a vendor.

        Without `overwrite`, fields the user already filled are left alone. The
        currency and the document type are the exceptions: both are properties
        of the document rather than judgement calls, so an extracted value
        always wins. Lines are replaced wholesale, never merged, because a
        half-updated line list would be worse than either version.
        """
        self.ensure_one()
        values = dict(values)
        currency_code = values.pop("currency_code", None)
        lines = values.pop("lines", None)
        authoritative = {
            name: values.pop(name)
            for name in ("document_type",)
            if name in values
        }
        if not overwrite:
            values = {
                name: value for name, value in values.items() if not self[name]
            }
        values.update(authoritative)
        if lines is not None and (overwrite or not self.line_ids):
            values["line_ids"] = [Command.clear()] + [
                Command.create(line) for line in lines
            ]
        if currency_code:
            currency = (
                self.env["res.currency"]
                .with_context(active_test=False)
                .search([("name", "=", currency_code)], limit=1)
            )
            if currency:
                values["currency_id"] = currency.id
        if values:
            self.write(values)
        self._match_partner()

    def _match_partner(self):
        """Link a res.partner by VAT, then by name. Never replaces a set vendor."""
        for record in self.filtered(lambda invoice: not invoice.partner_id):
            partner = self.env["res.partner"].browse()
            if record.partner_vat:
                partner = self.env["res.partner"].search(
                    [("vat", "=ilike", record.partner_vat.replace(" ", ""))], limit=1
                )
            if not partner and record.partner_name:
                partner = self.env["res.partner"].search(
                    [("name", "=ilike", record.partner_name)], limit=1
                )
            if partner:
                record.partner_id = partner

    @api.model
    def _json_safe(self, value):
        """Dates and other non-JSON values, rendered for extraction_payload."""
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, dict):
            return {name: self._json_safe(item) for name, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        return str(value)

    # ------------------------------------------------------------------
    # Mailbox ingestion
    # ------------------------------------------------------------------

    def _commit(self):
        """Persist the work done so far, mid-cron.

        Both crons work message by message and invoice by invoice, and each
        step has a cost outside the transaction — a mailbox flag flipped, an
        Azure analysis paid for. Committing after each keeps a later failure
        from throwing that away. Odoo forbids committing the test cursor, so
        the call is skipped while a test runs.
        """
        if not modules.module.current_test:
            self.env.cr.commit()

    @api.model
    def _mailbox_settings(self):
        params = self.env["ir.config_parameter"].sudo()
        return {
            "upn": params.get_param("invoice_inbound.mailbox"),
            "folder": params.get_param("invoice_inbound.folder") or "inbox",
            "processed_folder": params.get_param("invoice_inbound.processed_folder"),
        }

    @api.model
    def _is_invoice_attachment(self, attachment):
        if attachment.get("isInline"):
            return False
        name = (attachment.get("name") or "").lower()
        return (
            attachment.get("contentType") in INVOICE_MIMETYPES
            or name.endswith(INVOICE_EXTENSIONS)
        )

    @api.model
    def _cron_fetch_mailbox(self, limit=50):
        """Turn unread mail with a PDF or XML attachment into invoice records.

        Records are committed before the message is marked read, so a crash
        between the two costs a duplicate fetch — which the checksum catches —
        rather than a lost invoice.
        """
        settings = self._mailbox_settings()
        if not settings["upn"]:
            return
        mailbox = self.env["ms.graph.mailbox"]
        ok, messages = mailbox._list_messages(
            settings["upn"], folder=settings["folder"], unread_only=True
        )
        if not ok:
            _logger.warning(
                "invoice_inbound_fetch_failed",
                extra={
                    "event": "invoice_inbound_fetch_failed",
                    "mailbox": settings["upn"],
                    "error": messages,
                },
            )
            return

        for message in messages[:limit]:
            if not message.get("hasAttachments"):
                self._file_away(mailbox, settings, message, invoices=0)
                continue
            try:
                with self.env.cr.savepoint():
                    created = self._ingest_message(mailbox, settings["upn"], message)
            except Exception as e:
                _logger.exception(
                    "invoice_inbound_ingest_failed",
                    extra={
                        "event": "invoice_inbound_ingest_failed",
                        "mailbox": settings["upn"],
                        "message_id": message.get("id"),
                        "error": str(e),
                    },
                )
                continue
            # The records are safe on disk before the mailbox is touched.
            self._commit()
            self._file_away(mailbox, settings, message, invoices=len(created))

    @api.model
    def _ingest_message(self, mailbox, upn, message):
        """Create one invoice per usable attachment of `message`."""
        ok, attachments = mailbox._list_attachments(upn, message["id"])
        if not ok:
            raise UserError(attachments)

        sender = (
            (message.get("from") or {}).get("emailAddress") or {}
        ).get("address")
        created = self.browse()
        for attachment in attachments:
            if not self._is_invoice_attachment(attachment):
                continue
            ok, content = mailbox._fetch_attachment(upn, message["id"], attachment["id"])
            if not ok:
                raise UserError(content)
            checksum = self._checksum(content)
            duplicate = self.search_count(
                [
                    ("file_checksum", "=", checksum),
                    ("company_id", "=", self.env.company.id),
                ],
                limit=1,
            )
            if duplicate:
                _logger.info(
                    "invoice_inbound_duplicate_skipped",
                    extra={
                        "event": "invoice_inbound_duplicate_skipped",
                        "checksum": checksum,
                        "file_name": attachment.get("name"),
                    },
                )
                continue
            created |= self._create_from_file(
                content,
                attachment.get("name"),
                values={
                    "source": "email",
                    "email_from": sender,
                    "email_message_id": message.get("internetMessageId"),
                },
            )
        return created

    @api.model
    def _file_away(self, mailbox, settings, message, invoices):
        """Mark the message read and move it out of the way, best effort."""
        upn = settings["upn"]
        ok, error = mailbox._mark_read(upn, message["id"])
        if ok and settings["processed_folder"]:
            ok, error = mailbox._move_message(
                upn, message["id"], settings["processed_folder"]
            )
        if not ok:
            # The message stays unread, so the next run fetches it again and
            # the checksum turns the re-fetch into a no-op.
            _logger.warning(
                "invoice_inbound_file_away_failed",
                extra={
                    "event": "invoice_inbound_file_away_failed",
                    "mailbox": upn,
                    "message_id": message.get("id"),
                    "error": error,
                },
            )
            return
        _logger.info(
            "invoice_inbound_message_processed",
            extra={
                "event": "invoice_inbound_message_processed",
                "mailbox": upn,
                "message_id": message.get("id"),
                "invoices": invoices,
            },
        )

    @api.model
    def _cron_extract(self, limit=20):
        """Run OCR over the invoices no e-invoice could be read from.

        Does nothing until Document Intelligence is configured, so an install
        without an Azure resource leaves its invoices pending rather than
        marking every one of them failed.
        """
        endpoint = self.env["ir.config_parameter"].sudo().get_param(
            "azure_ai.di_endpoint"
        )
        if not endpoint:
            return
        invoices = self.search([("extraction_state", "=", "pending")], limit=limit)
        for invoice in invoices:
            try:
                with self.env.cr.savepoint():
                    invoice._extract()
            except Exception as e:
                _logger.exception(
                    "invoice_inbound_extraction_failed",
                    extra={
                        "event": "invoice_inbound_extraction_failed",
                        "invoice_id": invoice.id,
                        "error": str(e),
                    },
                )
                continue
            # Each analysis costs an API call; keep the ones already paid for.
            self._commit()
