from odoo.addons.rpc.controllers import RPC
from odoo.http import route
from werkzeug.exceptions import NotFound


class DisabledRPC(RPC):
    """Removes the deprecated XML-RPC and JSON-RPC endpoints."""

    @route()
    def jsonrpc(self, **kwargs):
        raise NotFound()

    @route()
    def xmlrpc_1(self, **kwargs):
        raise NotFound()

    @route()
    def xmlrpc_2(self, **kwargs):
        raise NotFound()
