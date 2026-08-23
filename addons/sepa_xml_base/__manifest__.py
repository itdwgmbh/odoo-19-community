{
    "name": "SEPA XML Base",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Read and create SEPA credit transfer and direct debit XML",
    "description": """
        Provides an AbstractModel `sepa.xml` other addons reuse to exchange
        ISO 20022 payment initiation files with a bank.

        - Create SEPA credit transfers (pain.001.001.09, pain.001.001.03)
        - Create SEPA direct debits (pain.008.001.08, pain.008.001.02)
        - Read either message back into plain Python values
        - EPC character set, IBAN, BIC and creditor identifier validation

        No accounting integration, no UI, no scheduled action: consumers map
        their own records onto the payload dict and own the bank transport.
    """,
    "author": "IT-DW GmbH",
    "website": "https://www.it-dw.com",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
