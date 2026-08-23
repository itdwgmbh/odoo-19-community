from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # The parameters live in azure_ai_base and invoice_inbound; this exposes
    # them so an administrator never has to edit system parameters by hand.
    azure_di_endpoint = fields.Char(
        string="Document Intelligence Endpoint",
        config_parameter="azure_ai.di_endpoint",
        help="Foundry / AI Services resource root, e.g. "
             "https://my-foundry.cognitiveservices.azure.com",
    )
    azure_di_timeout = fields.Integer(
        string="Analysis Timeout (s)",
        config_parameter="azure_ai.di_timeout",
        default=120,
    )
    invoice_inbound_mailbox = fields.Char(
        string="Invoice Mailbox",
        config_parameter="invoice_inbound.mailbox",
        help="UPN of the Microsoft 365 mailbox invoices are sent to. Leave "
             "empty to disable mailbox ingestion.",
    )
    invoice_inbound_folder = fields.Char(
        string="Source Folder",
        config_parameter="invoice_inbound.folder",
        default="inbox",
        help="Well-known folder name (inbox, archive, ...) or a folder id.",
    )
    invoice_inbound_processed_folder = fields.Char(
        string="Processed Folder",
        config_parameter="invoice_inbound.processed_folder",
        help="Folder ingested mail is moved to. Leave empty to only mark it read.",
    )
