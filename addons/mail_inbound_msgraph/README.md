# Inbound Mail via Microsoft Graph

Technical addon. Provides the AbstractModel `ms.graph.mailbox` for reading a
Microsoft 365 mailbox through Graph, on top of the shared `ms_graph_base`
client. It ships no mailbox configuration, no scheduled action and no UI —
consumers own those and call the functions they need.

## Configuration

None of its own. Configure the Entra credential — client secret, certificate,
managed identity or workload identity — as described in the `ms_graph_base`
README.

## Azure prerequisites

Application permissions on the app registration, with admin consent:

| Permission | Needed for |
| --- | --- |
| `Mail.ReadBasic.All` | `_list_messages`, `_delta_messages` |
| `Mail.Read` | `_get_message`, `_fetch_mime`, attachments, `_find_folder` |
| `Mail.ReadWrite` | `_mark_read`, `_move_message`, `_delete_message` |

`Mail.Read` covers reading; add `Mail.ReadWrite` only if a consumer marks,
moves or deletes messages. Restrict the app to the mailboxes it may touch
with `New-ApplicationAccessPolicy` (see the `mail_outbound_msgraph` README
for the PowerShell) — without it, the app reads every mailbox in the tenant.

## API

Every method takes the mailbox UPN first and returns `(ok, value)`:
`(True, value)` on success, `(False, error_message)` on failure, where the
error is Microsoft's `error.message` when parseable. This matches
`ms.graph.service._graph_request`, which already logs every failed request.

| Method | Returns |
| --- | --- |
| `_list_messages(upn, folder="inbox", unread_only=False, filter_=None, order=None, select=…, page_size=50, max_pages=20)` | list of message dicts |
| `_delta_messages(upn, folder="inbox", delta_link=None, select=…, page_size=50, max_pages=20)` | `{"messages", "removed_ids", "link", "complete"}` |
| `_get_message(upn, message_id, select=None)` | message dict |
| `_fetch_mime(upn, message_id)` | raw RFC822 bytes |
| `_list_attachments(upn, message_id, select=…)` | attachment metadata dicts |
| `_fetch_attachment(upn, message_id, attachment_id)` | raw attachment bytes |
| `_find_folder(upn, display_name, parent="msgfolderroot")` | folder id, or `None` when no match |
| `_mark_read(upn, message_id, read=True)` | updated message dict |
| `_move_message(upn, message_id, destination)` | new message id |
| `_delete_message(upn, message_id)` | `{}` |
| `_ingest_message(mime, model=None, custom_values=None, thread_id=None, save_original=False, strip_attachments=False)` | thread id, or `False` when Odoo ignored the message |

`folder` and `destination` accept a
[well-known folder name](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder)
(`inbox`, `archive`, `deleteditems`, `junkemail`, `sentitems`,
`msgfolderroot`, …) or a folder id. Pass `folder=None` to `_list_messages`
to search the whole mailbox. Custom folders need their id — resolve it once
with `_find_folder`, which searches the direct children of `parent`.

## Usage

Fetch, hand to Odoo's mail gateway, file the message away:

```python
mailbox = self.env["ms.graph.mailbox"]
upn = "support@example.com"

ok, messages = mailbox._list_messages(upn, unread_only=True)
if not ok:
    raise UserError(messages)

for msg in messages:
    ok, mime = mailbox._fetch_mime(upn, msg["id"])
    if not ok:
        continue  # left unread, retried next run
    ok, thread_id = mailbox._ingest_message(mime, model="helpdesk.ticket")
    if not ok:
        continue
    mailbox._move_message(upn, msg["id"], "archive")
```

Own parsing instead of the mail gateway:

```python
ok, mime = mailbox._fetch_mime(upn, message_id)
message = email.message_from_bytes(mime)
```

Incremental sync, storing the link in an `ir.config_parameter`:

```python
params = self.env["ir.config_parameter"].sudo()
ok, result = mailbox._delta_messages(upn, delta_link=params.get_param("my_addon.delta"))
if ok:
    for msg in result["messages"]:
        ...
    params.set_param("my_addon.delta", result["link"])
```

## Behaviour

- **Paging**: `_list_messages` and `_delta_messages` follow
  `@odata.nextLink` up to `max_pages` (20 × 50 = 1000 messages per call by
  default). Hitting the cap logs `ms_graph_inbound_list_truncated`; the
  remainder is read on the next call.
- **Partial results**: when a page after the first fails, the messages
  already collected are returned as a success and
  `ms_graph_inbound_list_partial` (or `…_delta_partial`) is logged. Only a
  failure on the very first page returns `(False, error)`.
- **Delta**: store `link` and pass it back as `delta_link`. `complete` is
  `False` when `max_pages` cut the round short — call again with the same
  link to continue. Graph reports an `@removed` entry when a message is
  deleted *or* moved out of the folder, and re-reports messages on unrelated
  changes such as read-state flips, so delta is at-least-once. Deduplicate on
  `internetMessageId`, which is stable across folders; the Graph `id` is not,
  because a move rewrites it.
- **Message ids**: `_move_message` returns the new id, since Graph implements
  a move as copy-then-remove and the old id dies with the original.
- **Deletion**: `_delete_message` is Graph's soft delete, to Deleted Items.
  The `permanentDelete` action is deliberately not exposed.
- **Attachment payloads**: listings request metadata only, so a mailbox full
  of large attachments does not land in one response. Pull payloads with
  `_fetch_attachment`, or take `_fetch_mime` and let the consumer's parser
  (or Odoo's) split it.
- **Ingestion**: `_ingest_message` delegates to
  `mail.thread.message_process`, which routes on aliases, `References` and
  `In-Reply-To` before falling back to `model`, and ignores any message whose
  `Message-Id` already exists in `mail.message` — so replayed delta rounds do
  not create duplicates. It runs inside a savepoint, so a rejected message
  leaves the caller's transaction usable, and returns `(False, error)`
  instead of raising.
- **Throttling and retries**: not handled here. A Graph 429 surfaces as a
  failed request; the consumer's cron decides when to try again.
- **Filters**: Graph rejects a `$filter` and `$orderby` on different
  properties, so pass at most one of `filter_` and `order`. `_delta_messages`
  supports neither: its only supported filter is on `receivedDateTime`, and
  it is not exposed.

## Logged events

`ms.graph.service` already logs every failed request as
`ms_graph_request_failed`. This addon logs only what that cannot show:

| event | when |
| --- | --- |
| `ms_graph_inbound_list_partial` | a listing page after the first failed; collected messages returned |
| `ms_graph_inbound_delta_partial` | same, during a delta round |
| `ms_graph_inbound_list_truncated` | `max_pages` reached with more pages pending |
| `ms_graph_inbound_ingest_failed` | `message_process` rejected a message |

## Tests

```bash
odoo -d <db> -i mail_inbound_msgraph --test-enable \
     --test-tags /mail_inbound_msgraph --stop-after-init
```

The suite mocks `ms.graph.service._graph_request`; it makes no network calls.
