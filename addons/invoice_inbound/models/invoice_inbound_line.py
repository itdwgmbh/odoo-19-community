from odoo import fields, models


class InvoiceInboundLine(models.Model):
    """One line item of an inbound invoice, as the document states it.

    Nothing is recomputed here: quantity times unit price need not equal the
    subtotal, because the document may carry a discount, a charge or a rounding
    the line itself does not spell out. What the extractor read is what is
    stored.
    """

    _name = "invoice.inbound.line"
    _description = "Inbound Invoice Line"
    _order = "invoice_id, sequence, id"

    invoice_id = fields.Many2one(
        "invoice.inbound", string="Invoice", required=True,
        ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(
        related="invoice_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="invoice_id.currency_id")
    sequence = fields.Integer(default=10)

    name = fields.Char(string="Description")
    product_code = fields.Char(string="Product Code")
    quantity = fields.Float(digits=(16, 4))
    uom = fields.Char(
        string="Unit",
        help="As stated by the document: a UN/ECE Rec 20 code from an "
             "e-invoice (H87, HUR, ...), free text from OCR.",
    )
    price_unit = fields.Monetary(string="Unit Price")
    tax_rate = fields.Float(string="Tax %", digits=(5, 2))
    amount = fields.Monetary(string="Subtotal")
    confidence = fields.Float(
        digits=(3, 2), readonly=True,
        help="Model confidence for an OCR line. 1 for an e-invoice line.",
    )
