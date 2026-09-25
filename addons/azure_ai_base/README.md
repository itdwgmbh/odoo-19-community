# Azure AI Base

Azure AI Document Intelligence client. Wraps the analyze long-running operation
and the field encoding of the response, so callers deal in plain Python values
and never in `valueCurrency` / `valueArray` shapes. It knows nothing about what
the fields mean — mapping `VendorName` to a business field is the caller's job.

Authentication is `ms.entra.auth` from `ms_graph_base`, so one identity serves
Graph and Azure resources alike and this addon owns no credentials.

## Configuration

`ir.config_parameter` keys (Settings → Technical → System Parameters):

| Key | Value |
| --- | --- |
| `azure_ai.di_endpoint` | Foundry / AI Services resource root, e.g. `https://my-foundry.cognitiveservices.azure.com` |
| `azure_ai.di_api_version` | Document Intelligence API version |
| `azure_ai.di_timeout` | Seconds to wait for an analysis |

Defaults are in `models/azure_document_intelligence.py`. Credentials are the
`ms_graph.*` keys — see the `ms_graph_base` README.

The 19.0.2.0.0 migration deletes the `azure_auth.*` keys. Where those pointed at
a different app registration than `ms_graph.*`, move the values to `ms_graph.*`
before upgrading.

## Azure setup

Document Intelligence data-plane calls are authorized by Azure RBAC, not by the
app registration's API permissions, so the identity needs a role assignment on
the Foundry resource:

```bash
az role assignment create \
  --assignee <CLIENT_ID_OR_PRINCIPAL_ID> \
  --role "Cognitive Services User" \
  --scope "/subscriptions/<SUB_ID>/resourceGroups/<RG>/providers/Microsoft.CognitiveServices/accounts/<RESOURCE>"
```

`Cognitive Services User` grants inference only. In managed- or
workload-identity mode assign the role to that identity's principal instead of
the app registration.

## Usage

The API is the `azure.document.intelligence` model in
`models/azure_document_intelligence.py`.

- `_analyze` blocks until the operation terminates or the timeout expires — run
  it from a cron or a queued job, not from a request handler.
- There are no retries. A 429 or 5xx surfaces as a failed call and the caller's
  cron decides when to try again.
