# Microsoft Graph Base

Shared OAuth2 + HTTP layer for any addon that calls `graph.microsoft.com`.
Owns the token cache and `_graph_request` helper; downstream addons
(e.g. `mail_outbound_msgraph`) only call the high-level methods they need.

## Configuration

Three `ir.config_parameter` keys (Settings → Technical → System Parameters):

| Key | Value |
| --- | --- |
| `ms_graph.tenant_id` | Azure AD tenant UUID |
| `ms_graph.client_id` | App registration client UUID |
| `ms_graph.client_secret` | App registration client secret |

## Azure app

One app registration can cover every Graph consumer. Grant only the
application permissions your addons use, e.g. `Mail.Send` for
`mail_outbound_msgraph`.

All application permissions need admin consent. Restrict mailbox access via
`New-ApplicationAccessPolicy` to a mail-enabled security group containing
the allowed mailboxes — otherwise the app can read/send mail as any user
in the tenant.

## Usage

```python
ok, body = self.env["ms.graph.service"]._graph_request(
    "POST", f"/users/{upn}/sendMail", json_data=payload
)
```

`_graph_request` returns `(True, body_dict)` on success — `body` is `{}` for
204 responses — and `(False, error_message)` on failure. The error message is
Microsoft's `error.message` when the response is parseable JSON, otherwise the
raw exception string. The caller is responsible for retries and chatter
notifications; the service only logs structured events
(`ms_graph_token_acquired`, `ms_graph_token_failed`,
`ms_graph_request_failed`).
