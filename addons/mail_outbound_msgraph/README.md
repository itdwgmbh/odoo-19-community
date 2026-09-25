# Outbound Mail via Microsoft Graph

Adds a `delivery_method` selection to `ir.mail_server`. When set to
`Microsoft Graph`, `send_email()` POSTs to `/users/{upn}/sendMail` via the
shared `ms_graph_base` client instead of opening an SMTP session. SMTP-method
servers are unaffected.

## Configuration

1. Install `ms_graph_base` and configure the Entra credential (see that addon's
   README).
2. On the production `ir.mail_server` record:
   - Set **Delivery Method** to *Microsoft Graph*.
   - Set **MS Graph Default Sender** to a real tenant mailbox UPN. This is the
     From used when a message's From header doesn't resolve to a tenant mailbox
     (cron mails, `noreply@`, etc.).

The dev/staging restore script (`odoo_restore/fixups.py`) keeps mail on
SMTP/MailDev — production cutover is a one-time UI edit and isn't part of
restores.

## Azure prerequisites

The app registration needs **Mail.Send** application permission with admin
consent. Without a scope restriction the app can send as any mailbox in the
tenant — restrict it with Exchange Online PowerShell:

```powershell
# Mail-enabled security group containing every mailbox Odoo may send from.
New-DistributionGroup -Name "odoo-mail-senders" -Type "Security" `
    -PrimarySmtpAddress "odoo-mail-senders@example.com"

Add-DistributionGroupMember -Identity "odoo-mail-senders" `
    -Member "odoo@example.com"

New-ApplicationAccessPolicy `
    -AppId <APP_CLIENT_ID> `
    -PolicyScopeGroupId "odoo-mail-senders@example.com" `
    -AccessRight RestrictAccess `
    -Description "Odoo outbound mail — restricted to odoo-mail-senders"
```

## Behaviour

- **From address**: taken from the MIME `From` header as Odoo set it.
- **Sender fallback**: on a sender-not-found error the send is retried once
  with the default sender.
- **Failures** raise `MailDeliveryException`, as with SMTP: the mail shows under
  *Sending Failures* and is resent from that dialog, since the mail queue cron
  only sends `outgoing` mails.
- **Sent Items**: mails are saved to the sender mailbox's Sent Items unless
  mailbox policy overrides it.
- **Attachments** are inlined in the request, so a message is limited by the
  Graph request size (about 4 MB); the upload-session flow is not implemented.
