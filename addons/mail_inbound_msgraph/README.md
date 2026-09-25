# Inbound Mail via Microsoft Graph

Technical addon. Provides the AbstractModel `ms.graph.mailbox` for reading a
Microsoft 365 mailbox through Graph, on top of the shared `ms_graph_base`
client. It ships no mailbox configuration, no scheduled action and no UI —
consumers own those and call the functions they need.

## Configuration

None of its own. Configure the Entra credential as described in the
`ms_graph_base` README.

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

The methods are on `ms.graph.mailbox` in `models/ms_graph_mailbox.py`. Each
takes the mailbox UPN first and returns `(True, value)` or
`(False, error_message)`, like `ms.graph.service._graph_request`.

## Behaviour

- **Paging**: listings follow `@odata.nextLink` up to `max_pages`; the
  remainder is read on the next call. When a page after the first fails, the
  messages already collected are returned as a success.
- **Delta**: store `link` and pass it back as `delta_link`. `complete` is
  `False` when `max_pages` cut the round short — call again with the same
  link to continue. Graph reports an `@removed` entry when a message is
  deleted *or* moved out of the folder, and re-reports messages on unrelated
  changes such as read-state flips, so delta is at-least-once. Deduplicate on
  `internetMessageId`, which is stable across folders; the Graph `id` is not,
  because a move rewrites it.
- **Custom folders** need their id; resolve it with `_find_folder`.
- **Deletion**: `_delete_message` is Graph's soft delete, to Deleted Items.
  `permanentDelete` is not exposed.
- **Ingestion**: `_ingest_message` delegates to
  `mail.thread.message_process`, which ignores any message whose `Message-Id`
  already exists in `mail.message`, so replayed delta rounds do not create
  duplicates. It runs inside a savepoint, so a rejected message leaves the
  caller's transaction usable.
- **Throttling and retries**: not handled here. A Graph 429 surfaces as a
  failed request; the consumer's cron decides when to try again.
- **Filters**: Graph rejects a `$filter` and `$orderby` on different
  properties, so pass at most one of `filter_` and `order`. `_delta_messages`
  supports neither.
