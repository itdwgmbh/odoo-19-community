# SEPA XML Base

Reads and creates the two ISO 20022 payment initiation messages a SEPA bank
account needs: credit transfers (pain.001) and direct debits (pain.008).
Downstream addons map their own records onto the payload dict below and own
the transport to the bank.

No configuration, no UI, no scheduled action.

## API

The methods are on `sepa.xml` in `models/sepa_xml.py`; `VERSIONS` and
`DEFAULT_VERSION` there list the versions written and the default per document
type. Pass `version=` for an older one when a bank still asks for it. `_parse`
reads any `pain.001.001.*` or `pain.008.001.*` document.

The build, parse and validate methods return `(True, value)` or
`(False, error_message)`; the error names the field and the payment block it
came from.

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

- **Totals**: `NbOfTxs` and `CtrlSum` are counted from the transactions.
  Values in the payload are ignored.
- **Character set**: every text field is mapped onto the SEPA Latin character
  set and truncated to the schema's length.
- **Validation**: a rejected payload produces no file.
- **Missing BIC**: an agent the schema makes mandatory carries the IBAN-only
  placeholder `<Othr><Id>NOTPROVIDED</Id></Othr>`; an optional one is omitted.
- **Remittance**: a `creditor_reference` is written as a structured `SCOR`
  creditor reference, otherwise `remittance_info` as one unstructured line.
  The rulebooks allow only one of the two.
- **Reading**: entity resolution, DTD loading and network access are off, so a
  file from a bank cannot pull in external content.
