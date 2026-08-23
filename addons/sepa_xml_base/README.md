# SEPA XML Base

Reads and creates the two ISO 20022 payment initiation messages a SEPA bank
account needs: credit transfers (pain.001) and direct debits (pain.008).
Downstream addons map their own records onto the payload dict below and own
the transport to the bank.

No configuration, no UI, no scheduled action.

## Versions

| Document | Default | Also written |
| --- | --- | --- |
| Credit transfer | `pain.001.001.09` | `pain.001.001.03` |
| Direct debit | `pain.008.001.08` | `pain.008.001.02` |

The defaults are the current EPC message versions; pass `version=` for the
older one when a bank still asks for it. `_parse` reads any `pain.001.001.*`
or `pain.008.001.*` document.

## API

| Method | Returns |
| --- | --- |
| `_build_credit_transfer(payload, version=None)` | pain.001 document as bytes |
| `_build_direct_debit(payload, version=None)` | pain.008 document as bytes |
| `_parse(source)` | the document as a dict |
| `_validate_iban(value)` | the IBAN without separators |
| `_validate_creditor_identifier(value)` | the creditor identifier |
| `_sanitize_text(value, max_length=None)` | text on the SEPA character set |

All but `_sanitize_text` return `(True, value)` or `(False, error_message)`.
The error message names the field and the payment block it came from, e.g.
`transaction 2 of payment block 1 creditor iban DE… fails the IBAN check
digits`.

```python
sepa = self.env["sepa.xml"]
ok, xml = sepa._build_credit_transfer({
    "message_id": "ODOO-2026-0042",
    "initiating_party": {"name": "Muster GmbH"},
    "payments": [{
        "requested_date": "2026-08-25",
        "debtor": {
            "name": "Muster GmbH",
            "iban": "DE89370400440532013000",
            "bic": "COBADEFFXXX",
        },
        "transactions": [{
            "end_to_end_id": "INV-2026-0001",
            "amount": "1234.56",
            "creditor": {"name": "Lieferant AG", "iban": "DE02120300000000202051"},
            "remittance_info": "Rechnung 2026-0001",
        }],
    }],
})
if not ok:
    raise UserError(xml)
```

## Payload

```python
{
    "message_id": "…",                  # generated when absent
    "creation_date_time": datetime,     # now when absent
    "initiating_party": {"name": "…", "identifier": "…"},
    "payments": [{
        "payment_id": "…",              # generated when absent
        "requested_date": date,         # today when absent
        "batch_booking": True,
        "charge_bearer": "SLEV",
        "service_level": "SEPA",
        "category_purpose": "SUPP",
        "debtor": {…},                  # credit transfer: who pays
        "creditor": {…},                # direct debit: who collects
        "creditor_scheme_id": "DE98ZZZ09999999999",   # direct debit
        "local_instrument": "CORE",     # direct debit, or B2B
        "sequence_type": "RCUR",        # direct debit: FRST/RCUR/OOFF/FNAL
        "ultimate_debtor": "…",         # credit transfer, name or party dict
        "ultimate_creditor": "…",       # direct debit, name or party dict
        "transactions": [{
            "end_to_end_id": "…",       # NOTPROVIDED when absent
            "instruction_id": "…",
            "amount": "1234.56",        # str, Decimal, int or float
            "currency": "EUR",
            "creditor": {…},            # credit transfer: who is paid
            "debtor": {…},              # direct debit: who is charged
            "remittance_info": "…",     # unstructured
            "creditor_reference": "RF…",# structured, wins over the above
            "purpose": "GDDS",
            "ultimate_creditor": "…",   # credit transfer
            "ultimate_debtor": "…",     # direct debit
            "mandate": {                # direct debit, required
                "id": "MNDT-0001",
                "signature_date": date,
                "amendment": {
                    "original_mandate_id": "…",
                    "original_creditor_scheme_id": "…",
                    "original_creditor_name": "…",
                    "original_debtor_iban": "…",
                    "same_mandate_new_debtor_account": True,
                },
            },
        }],
    }],
}
```

A party is `{"name", "iban", "bic", "country", "address_lines", "identifier"}`.
Only `name` and `iban` are required, `iban` not at all for an initiating or
ultimate party.

One payment block becomes one `PmtInf`. Group transactions into blocks the way
the scheme demands: a direct debit block carries a single collection date,
sequence type and local instrument, so a run that mixes `FRST` and `RCUR`
needs a block per sequence type.

`_parse` returns `{"document_type", "version", "namespace", "group_header",
"payments"}` where `group_header` holds `message_id`, `creation_date_time`,
`number_of_transactions`, `control_sum` and `initiating_party`. Payments and
transactions come back in the payload shape above, so a parsed document can be
edited and written back — in another version if needed. Amounts are `Decimal`,
dates are `date`, timestamps are timezone-aware `datetime`, and keys the
document does not carry are absent.

## Behaviour

- **Totals**: `NbOfTxs` and `CtrlSum` are counted from the transactions, per
  payment block and for the group header. Values in the payload are ignored.
- **Character set**: every text field is mapped onto the SEPA Latin character
  set — `ä`→`ae`, `ß`→`ss`, `&`→`+`, accents dropped, anything else replaced by
  a space — then truncated to the schema's length (name 70, identifier 35,
  remittance 140, two address lines of 70).
- **Validation**: IBAN and creditor identifier check digits (ISO 7064 mod 97),
  BIC shape, amount greater than zero and at most 999999999.99, ISO 3166
  country, ISO 4217 currency, ISO 20022 codes. A rejected payload produces no
  file.
- **Missing BIC**: an agent the schema makes mandatory carries the IBAN-only
  placeholder `<Othr><Id>NOTPROVIDED</Id></Othr>`; an optional one is omitted.
- **Version differences**: `pain.001.001.09` wraps the execution date in
  `<ReqdExctnDt><Dt>` and names the agent `BICFI` where `pain.001.001.03` uses
  a bare date and `BIC`; `pain.008.001.08` carries the same-mandate-new-account
  flag `SMNDA` in `OrgnlDbtrAcct`, `pain.008.001.02` in `OrgnlDbtrAgt`.
- **Remittance**: a `creditor_reference` is written as a structured `SCOR`
  creditor reference, otherwise `remittance_info` as one unstructured line.
  The rulebooks allow only one of the two.
- **Reading**: entity resolution, DTD loading and network access are off, so a
  file from a bank cannot pull in external content.

Documents built in all four versions validate against the ISO 20022 schemas,
and a document read back and rewritten reproduces the file it came from.

## Logged events

| event | when |
| --- | --- |
| `sepa_build_failed` | a payload was rejected, with the field at fault |
| `sepa_parse_failed` | a document was malformed or not a SEPA message |

## Tests

```bash
odoo -d <db> -i sepa_xml_base --test-enable \
     --test-tags /sepa_xml_base --stop-after-init
```
