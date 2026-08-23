{
    "name": "Microsoft Graph Base",
    "version": "19.0.2.1.0",
    "category": "Tools",
    "summary": "Entra ID authentication + low-level request layer for Microsoft Graph",
    "description": """
        Provides two AbstractModels other addons reuse.

        `ms.entra.auth` — application tokens for any Azure resource, via
        `_get_token(scope)` / `_auth_headers(scope)`:

        - Client secret, certificate, managed identity (system- and
          user-assigned), or federated workload identity (AKS)
        - Per-worker token cache, keyed by identity and scope
        - Credentials read from ir.config_parameter (ms_graph.auth_mode,
          ms_graph.tenant_id, ms_graph.client_id, ...)

        `ms.graph.service` — generic
        `_graph_request(method, path, json_data=None, raw=False)` against
        graph.microsoft.com, authenticated through `ms.entra.auth`.
    """,
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "depends": ["base"],
    "external_dependencies": {"python": ["cryptography", "jwt"]},
    "installable": True,
    "application": False,
    "auto_install": False,
}
