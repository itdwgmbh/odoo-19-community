{
    "name": "IT-DW JSON-2 JWT Authentication",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Accept signed JWTs alongside API keys on the JSON-2 API",
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "depends": ["rpc"],
    "external_dependencies": {"python": ["jwt", "cryptography"]},
    "data": [
        "security/ir.model.access.csv",
        "data/jwt_issuer.xml",
        "views/jwt_issuer_views.xml",
    ],
    "installable": True,
    "application": False,
}
