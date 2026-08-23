{
    "name": "Azure AI Base",
    "version": "19.0.2.0.0",
    "category": "Technical",
    "summary": "Azure AI Document Intelligence client",
    "description": """
        Provides the AbstractModel `azure.document.intelligence` other addons
        reuse to analyze documents with a Document Intelligence model
        (prebuilt-invoice, prebuilt-receipt, custom, ...) and to read the
        returned fields as plain Python values.

        Authentication is `ms.entra.auth` from ms_graph_base, so one identity
        and one set of credentials serve Graph and Azure resources alike.
        Endpoint and API version come from ir.config_parameter
        (azure_ai.di_endpoint, azure_ai.di_api_version, azure_ai.di_timeout).
    """,
    "author": "IT-DW GmbH",
    "website": "https://www.it-dw.com",
    "license": "LGPL-3",
    "depends": ["ms_graph_base"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
