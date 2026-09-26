{
    "name": "IT-DW JWT API Authentication",
    "version": "19.0.2.0.0",
    "category": "Technical",
    "summary": "Accept signed JWTs as bearer tokens and disable XML-RPC and JSON-RPC",
    "author": "IT-DW GmbH",
    "license": "LGPL-3",
    "depends": ["rpc"],
    "external_dependencies": {"python": ["PyJWT", "cryptography"]},
    "data": [
        "security/ir.model.access.csv",
        "data/jwt_issuer.xml",
        "views/jwt_issuer_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
