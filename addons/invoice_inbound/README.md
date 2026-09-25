# Inbound Invoice Management

One `invoice.inbound` record per incoming supplier invoice. Each record holds
the file, the header fields read out of it, and the state it has reached:

```
Incoming ──▶ Validated ──▶ Paid
    ▲            │
    └──▶ Rejected ┘
```

`Paid` is reachable only from `Validated`. Any state can be reset to
`Incoming`, which clears the payment date and the rejection reason.

A credit note runs through the same states. It is recognised from the document
and its total counts negatively in list sums, so a mixed list adds up to what is
actually owed.

The addon files and tracks invoices. It posts nothing to Accounting — no
`account.move` is created and `account` is not a dependency.

## Configuration

Settings → Invoice Inbox. Odoo restricts `res.config.settings` to
*Administration: Settings*, so an Invoice Inbox manager without it cannot open
the page:

| Setting | Parameter | Purpose |
| --- | --- | --- |
| Document Intelligence Endpoint | `azure_ai.di_endpoint` | Foundry resource root. Empty disables OCR. |
| Analysis Timeout (s) | `azure_ai.di_timeout` | Wait budget per analysis |
| Invoice Mailbox | `invoice_inbound.mailbox` | Mailbox UPN. Empty disables mailbox ingestion. |
| Source Folder | `invoice_inbound.folder` | Well-known folder name or folder id |
| Processed Folder | `invoice_inbound.processed_folder` | Where ingested mail is moved. Empty means mark read only. |

Entra credentials are the `ms_graph.*` keys owned by `ms_graph_base`, shared
with the mailbox side. `azure_ai_base` adds only the endpoint, and its README
covers the **Cognitive Services User** role assignment the Foundry resource
needs.

Mailbox access goes through `ms_graph_base` / `mail_inbound_msgraph`. The app
registration needs `Mail.Read` — plus `Mail.ReadWrite`, because every ingested
message is marked read and optionally moved.

## Scheduled actions

*Invoice Inbox: Fetch Mailbox* turns unread mail with a PDF or XML attachment
into invoices; *Invoice Inbox: Extract Fields* runs OCR over pending invoices.
Both are enabled on install and no-op until configured.

## Field extraction

Two extractors, tried in that order:

1. **E-invoice** — CII (ZUGFeRD 2.x, Factur-X, XRechnung) and UBL (XRechnung,
   Peppol BIS Billing), read from a standalone XML file or from the XML
   embedded in a PDF/A-3. Local, no network, so it runs the moment
   the record is created and the upload comes back with its fields filled in.
   Confidence is always 1: the fields are read, not recognised.
2. **Azure Document Intelligence** — everything else, via the
   `prebuilt-invoice` model. This one costs an API call and takes seconds, so
   it is left to the *Extract Fields* cron. **Extract Again** on the form runs
   it on demand.

Both fill the header fields and the line items. Nothing is recomputed —
quantity times unit price need not equal the subtotal, because a line may carry
a discount or rounding it does not spell out.

The **Unit** column spells out the UN/ECE Rec 20 code an e-invoice carries
(`H87` reads as *piece*, `HUR` as *hour*). The raw code stays on the line as
**Unit Code**, hidden by default. A code outside the commercial subset, and the
free text OCR returns, are shown unchanged rather than guessed at. Note that the
code is whatever the sender wrote: a document stating `H87` for work billed by
the hour is wrong at source, and this addon reports it faithfully rather than
correcting it.

The **Lines** tab totals the subtotals and says so when they do not add up to
the untaxed amount. A document-level discount or charge makes them differ
legitimately, which is why it is a note and not an error.

### Credit notes

- **E-invoice**: from the UNTDID 1001 type code (`CREDIT_NOTE_CODES` in
  `models/invoice_einvoice_parser.py`) or a UBL `CreditNote` root element.
- **OCR**: `prebuilt-invoice` has no document-type field, so a credit note is
  recognised only by a negative total. Where the layout does not produce one,
  set **Document Type** by hand.
- **Amounts** are stored as the document prints them, positive on a credit note
  too, the way EN16931 states them. The sign lives in **Signed Total**, which is
  what list views sum.

### Details

- **Vendor matching**: after extraction the record is linked to a
  `res.partner` matching on VAT (spaces stripped), then on the name
(case-insensitive). A
  vendor already set by hand is never replaced.
- **Overwriting**: automatic extraction fills only empty fields, so a hand
  correction survives. **Extract Again** overwrites. Currency and document type
  are the exceptions and always come from the document, which is authoritative
  about what it is and what it is denominated in. Lines are replaced wholesale
  rather than merged, and only when the invoice has none yet or **Extract
  Again** was pressed.
- **VAT vs. tax number**: a German seller sends both. CII picks the
  registration with `schemeID="VA"`; UBL picks the `PartyTaxScheme` whose
  `TaxScheme/ID` is `VAT`. Where a seller reports only one, that one is used.
- **Confidence**: `extraction_confidence` is the model's confidence for the
  document. The **Extraction** tab shows per-field values and confidences as
  the extractor returned them.
- **ZUGFeRD 1.0** uses different element names and is not supported. Such a PDF
  falls through to OCR, as does an e-invoice whose XML parses but holds nothing
  readable.
- **Untrusted XML**: entity resolution, DTD loading and network access are off
  in the parser, since these files arrive by mail.

## Mailbox ingestion

Every unread message in the source folder is examined. Each PDF or XML
attachment becomes one invoice; inline attachments are skipped.

- **Ordering**: the records are committed *before* the message is marked read.
  A crash between the two costs a re-fetch on the next run, not an invoice.
- **Duplicates**: a file whose SHA-256 already exists in the company is
  skipped, which is what makes that re-fetch harmless.
- **Failures**: a message that cannot be read is left unread and untouched, and
  the run continues with the next one. A failed mark-read means the message is
  not moved either, so the pair never comes apart.
- **Commits**: each message is committed on its own.
- **Multi-company**: the mailbox is one global setting, so every ingested
  invoice lands in the cron user's company. Several companies feeding separate
  mailboxes are not supported.

## Access

| Group | Can |
| --- | --- |
| Invoice Inbox / User | read, create and edit invoices and their lines |
| Invoice Inbox / Manager | the above, plus change status, archive and delete |

`state`, `active` and `payment_date` are gated in `write` and `create`, not only
on the buttons: `groups=` on a button hides it in the form while leaving the RPC
behind it callable, and a plain write would bypass the state machine entirely.
Without the gate an Invoice Inbox user could mark a supplier invoice paid
without it ever having been validated.

Records are visible only within the user's allowed companies. Opening the
settings page additionally needs *Administration: Settings*.
