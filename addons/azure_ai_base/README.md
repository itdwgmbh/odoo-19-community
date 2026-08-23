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
| `azure_ai.di_endpoint` | Foundry / AI Services endpoint, e.g. `https://my-foundry.cognitiveservices.azure.com` |
| `azure_ai.di_api_version` | Document Intelligence API version (default `2024-11-30`) |
| `azure_ai.di_timeout` | Seconds to wait for an analysis (default `120`) |

Credentials are the `ms_graph.*` keys — see the `ms_graph_base` README for the
mode you want (client secret, certificate, managed identity, workload
identity). Nothing extra is configured here, and `ms_graph_base`'s
`neutralize.sql` already clears them on a neutralized restore.

Upgrading from 1.x drops the `azure_auth.*` keys the old built-in auth service
read. Where those pointed at a different app registration than `ms_graph.*`,
move the values across before upgrading.

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

`Cognitive Services User` grants inference only. It does not allow reading the
resource keys or changing the deployment. In managed- or workload-identity mode
assign the role to that identity's principal instead of the app registration.

## API

| Method | Returns |
| --- | --- |
| `_analyze(model_id, content, locale=None, pages=None)` | the service's `analyzeResult` object |
| `_document_fields(analyze_result, index=0)` | `{name: {"value", "confidence", "content"}}` |
| `_document_confidence(analyze_result, index=0)` | model confidence for the document |

`_analyze` returns `(True, analyze_result)` or `(False, error_message)`, the
same convention as `ms.entra.auth` and `ms.graph.service`. `_document_fields`
and `_document_confidence` return their value directly and give `{}` / `None`
when the model recognised no document.

```python
di = self.env["azure.document.intelligence"]
ok, result = di._analyze("prebuilt-invoice", pdf_bytes)
if not ok:
    raise UserError(result)
fields = di._document_fields(result)
vendor = (fields.get("VendorName") or {}).get("value")
total = (fields.get("InvoiceTotal") or {}).get("value")  # {"amount": …, "currencyCode": …}
```

## Behaviour

- **Long-running operation**: `_analyze` POSTs the document as `base64Source`,
  reads `Operation-Location` from the 202, then polls until the operation
  reports `succeeded`, `failed` or `canceled`. It honours the service's
  `Retry-After` header and gives up after `azure_ai.di_timeout` seconds. The
  call blocks — run it from a cron or a queued job, not from a request handler
  serving a page.
- **Token**: fetched per poll rather than once, so a long analysis cannot fail
  on an expiry mid-loop. `ms.entra.auth` serves it from its per-worker cache.
- **Field decoding**: `_field_value` maps a `DocumentField` to a plain value by
  its `type` — arrays to lists and objects to dicts, both recursively.
  `currency` keeps `{"amount", "currencyCode"}` and `address` keeps its
  components, because in both cases the parts carry meaning separately. An
  unrecognised type falls back to the field's matched text.
- **Endpoint**: `azure_ai.di_endpoint` is the resource root; `_analyze` appends
  `/documentintelligence/documentModels/{model_id}:analyze` itself.
- **Retries**: none. A 429 or 5xx surfaces as a failed call and the caller's
  cron decides when to try again.

## Logged events

| event | when |
| --- | --- |
| `azure_di_analyze_failed` | submission or the operation itself failed |
| `azure_di_analyze_timeout` | the operation did not terminate within the budget |

Token acquisition is logged by `ms.entra.auth`.

## Tests

```bash
odoo -d <db> -i azure_ai_base --test-enable \
     --test-tags /azure_ai_base --stop-after-init
```

The suite patches `requests` and `ms.entra.auth`; it makes no network calls.
