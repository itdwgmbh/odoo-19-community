# Microsoft Graph Base

Shared Microsoft Entra ID authentication and HTTP layer. Provides two
AbstractModels:

- `ms.entra.auth` — application tokens for any Azure resource, from a client
  secret, a certificate, the platform's managed identity, or a federated
  workload identity (AKS).
- `ms.graph.service` — `_graph_request` against `graph.microsoft.com`,
  authenticated through `ms.entra.auth`.

Downstream addons (`mail_outbound_msgraph`, `mail_inbound_msgraph`) call the
high-level methods they need and own no credentials.

Requires `cryptography` and `PyJWT`, both present in the bundled image.

## Configuration

`ir.config_parameter` keys (Settings → Technical → System Parameters):

| Key | Value |
| --- | --- |
| `ms_graph.auth_mode` | `client_secret` (default), `certificate`, `managed_identity` |
| `ms_graph.tenant_id` | Tenant UUID or domain — secret and certificate modes |
| `ms_graph.client_id` | App registration client UUID — secret and certificate modes |
| `ms_graph.client_secret` | Client secret — secret mode |
| `ms_graph.certificate` | PEM bundle (private key + certificate), or base64 of a PEM or PKCS#12 file — certificate mode |
| `ms_graph.certificate_path` | Path to a PEM or PKCS#12 file; takes precedence over `ms_graph.certificate` |
| `ms_graph.certificate_password` | Passphrase for an encrypted PEM key or a `.pfx` |
| `ms_graph.managed_identity_client_id` | User-assigned identity client UUID; empty selects the system-assigned identity |
| `ms_graph.federated_token_file` | Path to the projected token; overrides `AZURE_FEDERATED_TOKEN_FILE` — workload identity mode |
| `ms_graph.authority` | Login endpoint, default `https://login.microsoftonline.com` |

Keys the active mode does not use are ignored.

## Modes

**`client_secret`** — one secret in the database, expires on the schedule Entra
enforces (24 months maximum).

**`certificate`** — no shared secret leaves the host when
`ms_graph.certificate_path` points at a file readable only by the Odoo user.
Generate a key pair, upload the public half to the app registration under
Certificates & secrets → Certificates, keep the bundle on the host:

```bash
openssl req -x509 -newkey rsa:2048 -days 730 -nodes \
        -keyout key.pem -out cert.pem -subj "/CN=odoo"
cat key.pem cert.pem > /etc/odoo/entra.pem   # ms_graph.certificate_path
base64 -w0 /etc/odoo/entra.pem               # or paste into ms_graph.certificate
```

Entra requires an RSA key; the certificate must be present alongside it,
because its SHA-1 thumbprint identifies the credential to Entra. The file is
re-read on each token acquisition, so replacing it needs no restart.

**`managed_identity`** — no credential at all. Available when Odoo runs on an
Azure VM, VMSS, Container App, App Service or Function. Set
`ms_graph.auth_mode` and nothing else for the system-assigned identity; add
`ms_graph.managed_identity_client_id` to select a user-assigned one. Tenant and
client id are not read in this mode. On AKS this reaches the node's kubelet
identity, which is shared by every pod on the node — use `workload_identity`
instead.

**`workload_identity`** — no credential at all, per pod. For Odoo on AKS with
[Azure Workload Identity](https://azure.github.io/azure-workload-identity/)
enabled. Kubernetes projects a short-lived service account token into the pod;
this mode exchanges it for an Entra token and re-reads the file on every
acquisition, so rotation is transparent.

Set `ms_graph.auth_mode` and nothing else: the admission webhook injects
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_FEDERATED_TOKEN_FILE` and
`AZURE_AUTHORITY_HOST`. The matching config parameters override the injected
values when set.

The cluster side needs a federated credential on the app registration, plus a
service account and pod bound to it:

```bash
az identity federated-credential create --name odoo \
    --identity-name <managed-identity> --resource-group <rg> \
    --issuer "$(az aks show -g <rg> -n <cluster> --query oidcIssuerProfile.issuerUrl -o tsv)" \
    --subject system:serviceaccount:<namespace>:<serviceaccount> \
    --audience api://AzureADTokenExchange
```

```yaml
# ServiceAccount: annotate with the identity's client id
metadata:
  annotations:
    azure.workload.identity/client-id: <client-uuid>
---
# Pod template: opt in to the webhook
metadata:
  labels:
    azure.workload.identity/use: "true"
spec:
  serviceAccountName: <serviceaccount>
```

An app registration works in place of a managed identity: add the federated
credential under Certificates & secrets → Federated credentials.

Graph application permissions cannot be granted to a managed identity in the
portal — assign the app role to its service principal:

```powershell
Connect-MgGraph -Scopes AppRoleAssignment.ReadWrite.All,Application.Read.All
$graph = Get-MgServicePrincipal -Filter "appId eq '00000003-0000-0000-c000-000000000000'"
$role  = $graph.AppRole | Where-Object Value -eq 'Mail.Read'
New-MgServicePrincipalAppRoleAssignment -ServicePrincipalId <identity-object-id> `
    -PrincipalId <identity-object-id> -ResourceId $graph.Id -AppRoleId $role.Id
```

## Azure app

One app registration can cover every Graph consumer. Grant only the
application permissions your addons use, e.g. `Mail.Send` for
`mail_outbound_msgraph`.

All application permissions need admin consent. Restrict mailbox access via
`New-ApplicationAccessPolicy` to a mail-enabled security group containing
the allowed mailboxes — otherwise the app can read/send mail as any user
in the tenant.

## Usage

Graph, through the request helper:

```python
ok, body = self.env["ms.graph.service"]._graph_request(
    "POST", f"/users/{upn}/sendMail", json_data=payload
)
```

Any other Azure API, through the token service:

```python
auth = self.env["ms.entra.auth"]
ok, headers = auth._auth_headers("https://vault.azure.net/.default")
if ok:
    resp = requests.get(f"{vault}/secrets/{name}?api-version=7.4", headers=headers)
```

| Method | Returns |
| --- | --- |
| `_get_token(scope)` | access token |
| `_auth_headers(scope)` | `{"Authorization": "Bearer …"}` |
| `_invalidate_token(scope=None)` | drops this worker's cached tokens |
| `_graph_request(method, path, json_data=None, raw=False)` | decoded JSON, `{}` on 204, or bytes when `raw=True` |

`scope` accepts either form — `https://graph.microsoft.com/.default` or the
bare resource `https://graph.microsoft.com`; both are normalised per mode and
share one cache entry.

## Behaviour

- **Return convention**: every method returns `(True, value)` or
  `(False, error_message)`. The error is Microsoft's `error_description`
  (token endpoint) or `error.message` (Graph) when the body is parseable JSON,
  otherwise the raw exception string.
- **Token cache**: per Odoo worker, keyed by mode, authority, tenant, client id
  and scope, so several resources and a changed identity never share an entry.
  A token is reused until 120 s before it expires. One acquisition runs at a
  time per worker, so a burst of requests makes one token call.
- **Retries**: none. A throttled or transient failure surfaces to the caller,
  whose cron decides when to try again.
- **Azure Arc** managed identity is not supported; its challenge-response flow
  needs a key file the Odoo user cannot read.

## Logged events

| event | when |
| --- | --- |
| `ms_entra_token_acquired` | token issued; carries mode, tenant, client id, scope, lifetime |
| `ms_entra_token_failed` | acquisition failed; carries the same fields plus the error |
| `ms_graph_request_failed` | a Graph request returned an error |

Secrets, certificates and tokens are never logged.

## Neutralize

`data/neutralize.sql` clears every stored credential and forces
`ms_graph.auth_mode` back to `client_secret`, so a neutralized copy — including
one restored on the Azure host or in the AKS pod whose identity would otherwise
still work — cannot authenticate against production Microsoft 365.

## Tests

```bash
odoo -d <db> -i ms_graph_base --test-enable \
     --test-tags /ms_graph_base --stop-after-init
```

The suite mocks `requests`; it makes no network calls.
