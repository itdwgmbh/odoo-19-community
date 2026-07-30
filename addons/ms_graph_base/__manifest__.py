{
    "name": "Microsoft Graph Base",
    "version": "19.0.1.1.0",
    "category": "Tools",
    "summary": "Shared OAuth2 client + low-level request layer for Microsoft Graph",
    "description": """
        Provides an AbstractModel `ms.graph.service` other addons reuse to talk
        to graph.microsoft.com.

        - Client-credentials OAuth2 flow (per-worker token cache, 58 min TTL)
        - Generic `_graph_request(method, path, json_data=None)` helper
        - Credentials read from ir.config_parameter:
          ms_graph.tenant_id, ms_graph.client_id, ms_graph.client_secret

    """,
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
