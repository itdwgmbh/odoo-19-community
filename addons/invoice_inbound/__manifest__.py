{
    "name": "Inbound Invoice Management",
    "version": "19.0.1.1.0",
    "category": "Accounting",
    "summary": "Inbox for supplier invoices with e-invoice and OCR field extraction",
    "description": """
        One record per incoming supplier invoice, moving through Incoming,
        Validated, Rejected and Paid.

        - Invoices arrive by manual upload or from a Microsoft 365 mailbox
          polled through Microsoft Graph.
        - Header fields and line items are read from an embedded or standalone
          e-invoice (ZUGFeRD 2.x / Factur-X CII, XRechnung, Peppol BIS 3 UBL).
        - Everything else is sent to Azure AI Document Intelligence
          (prebuilt-invoice) for OCR and parsing.
        - Credit notes are recognised and their totals count negatively.

        The addon stores and tracks invoices; it posts nothing to Accounting.
    """,
    "author": "IT-DW GmbH",
    "website": "https://www.it-dw.com",
    "license": "LGPL-3",
    "depends": ["mail", "mail_inbound_msgraph", "azure_ai_base"],
    "data": [
        "security/invoice_inbound_groups.xml",
        "security/ir.model.access.csv",
        "security/invoice_inbound_security.xml",
        "views/invoice_inbound_views.xml",
        "views/res_config_settings_views.xml",
        "views/invoice_inbound_menus.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
