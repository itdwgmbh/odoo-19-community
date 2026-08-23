{
    "name": "Inbound Mail via Microsoft Graph",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Read and ingest mailbox messages through Microsoft Graph",
    "description": """
        Provides an AbstractModel `ms.graph.mailbox` other addons reuse to
        read mail from a Microsoft 365 mailbox.

        - List, delta-sync, and fetch messages (JSON or raw RFC822 MIME)
        - Fetch attachments without downloading the whole message
        - Mark read, move between folders, delete
        - Hand raw MIME to Odoo's mail gateway (mail.thread.message_process)

        No mailbox configuration, no scheduled action, no UI: consumers own
        their own configuration and cron.
    """,
    "author": "IT-DW GmbH",
    "website": "https://www.it-dw.com",
    "license": "LGPL-3",
    "depends": ["mail", "ms_graph_base"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
