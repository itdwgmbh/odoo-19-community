# Outbound Mail via Microsoft Graph

Adds a `delivery_method` selection to `ir.mail_server`. When set to
`Microsoft Graph`, `send_email()` POSTs to `/users/{upn}/sendMail` via the
shared `ms_graph_base` client instead of opening an SMTP session.

SMTP-method servers (e.g. MailDev in dev) are unaffected — the override is
gated entirely on `delivery_method`.

## Configuration

1. Install `ms_graph_base` and configure `ms_graph.tenant_id`,
   `ms_graph.client_id`, `ms_graph.client_secret` (see that addon's README).
2. On the production `ir.mail_server` record:
   - Set **Delivery Method** to *Microsoft Graph*.
   - Set **MS Graph Default Sender** to a real tenant mailbox UPN (e.g.
     `odoo@example.com`). This is the From used when a message's From header
     doesn't resolve to a tenant mailbox (cron mails, `noreply@`, etc.).

The dev/staging restore script (`odoo_restore/fixups.py`) keeps mail on
SMTP/MailDev — production cutover is a one-time UI edit and isn't part of
restores.

## Azure prerequisites

The app registration needs **Mail.Send** application permission with admin
consent. Without a scope restriction the app can send as any mailbox in the
tenant — restrict it:

```powershell
# Create a mail-enabled security group containing every mailbox Odoo is
# allowed to send from (initially: just the shared odoo@ mailbox).
New-DistributionGroup -Name "odoo-mail-senders" -Type "Security" `
    -PrimarySmtpAddress "odoo-mail-senders@example.com"

Add-DistributionGroupMember -Identity "odoo-mail-senders" `
    -Member "odoo@example.com"

# Restrict the Odoo app to that group.
New-ApplicationAccessPolicy `
    -AppId <APP_CLIENT_ID> `
    -PolicyScopeGroupId "odoo-mail-senders@example.com" `
    -AccessRight RestrictAccess `
    -Description "Odoo outbound mail — restricted to odoo-mail-senders"
```

Apply via the Exchange Online PowerShell module.

## Behaviour

- **From address**: parsed from the MIME `From` header. Whatever Odoo set
  goes into the URL path — no template-rewriting is done here.
- **Sender fallback**: if Graph returns a sender-not-found error
  (`ResourceNotFound`, `MailboxNotEnabled`, …), the send is retried once
  with `ms_graph_default_sender`. A `ms_graph_send_fallback_sender` event is
  logged each time this triggers.
- **Other errors** (auth, throttling, payload validation) raise
  `MailDeliveryException`, which `mail.mail` records as `exception` for the
  scheduled retry cron to pick up — same behaviour as the SMTP transport.
- **Sent Items**: `saveToSentItems: true` — mails appear in the sender
  mailbox's Outlook Sent Items unless mailbox policy overrides it.
- **Message-Id**: reused from the incoming MIME message so threading in
  recipient clients still works (Graph's `sendMail` returns no body).
- **Attachments**: inlined as base64. Total Graph payload limit is ~4 MB;
  larger attachments would need the upload-session flow (not implemented —
  no current mail flow approaches this).

## Logged events

| event | when |
| --- | --- |
| `msgraph_mail_sent` | success |
| `msgraph_send_failed` | non-recoverable failure (raised) |
| `ms_graph_send_fallback_sender` | retried with default sender after a sender-not-found error |
