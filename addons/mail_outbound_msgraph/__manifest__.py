{
    "name": "Outbound Mail via Microsoft Graph",
    "version": "19.0.1.0.1",
    "category": "Tools",
    "summary": "Send outbound mail through Microsoft Graph sendMail instead of SMTP",
    "description": """
        Adds a delivery_method field to ir.mail_server. When set to
        'msgraph', send_email routes through Microsoft Graph's
        /users/{upn}/sendMail endpoint instead of opening an SMTP session.
        SMTP servers (e.g. MailDev in dev) are unaffected.
    """,
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "depends": ["mail", "ms_graph_base"],
    "data": [
        "views/ir_mail_server_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
