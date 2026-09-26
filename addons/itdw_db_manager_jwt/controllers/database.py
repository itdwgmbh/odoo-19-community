import re

from odoo import http
from odoo.addons.itdw_db_backup_age.controllers.database import DatabaseAge
from odoo.http import request
from werkzeug.exceptions import NotFound

_BEARER = re.compile(r"^bearer\s+(.+)$", re.IGNORECASE)
_SCRIPT = (
    '<script src="/itdw_db_manager_jwt/static/src/database_manager_jwt.js"></script>'
)


def _credential(master_pwd):
    header = request.httprequest.headers.get("Authorization", "")
    match = _BEARER.match(header)
    return match.group(1) if match else master_pwd


class DatabaseJWT(DatabaseAge):
    def _render_template(self, **values):
        page = super()._render_template(**values)
        return str(page).replace("</body>", f"{_SCRIPT}</body>")

    @http.route("/web/database/selector", type="http", auth="none")
    def selector(self, **kw):
        return super().selector(**kw)

    @http.route("/web/database/manager", type="http", auth="none")
    def manager(self, **kw):
        return super().manager(**kw)

    @http.route(
        "/web/database/create", type="http", auth="none", methods=["POST"], csrf=False
    )
    def create(self, master_pwd=None, **kw):
        return super().create(_credential(master_pwd), **kw)

    @http.route(
        "/web/database/duplicate",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def duplicate(self, master_pwd=None, **kw):
        return super().duplicate(_credential(master_pwd), **kw)

    @http.route(
        "/web/database/drop", type="http", auth="none", methods=["POST"], csrf=False
    )
    def drop(self, master_pwd=None, **kw):
        return super().drop(_credential(master_pwd), **kw)

    @http.route(
        "/web/database/backup", type="http", auth="none", methods=["POST"], csrf=False
    )
    def backup(self, master_pwd=None, **kw):
        return super().backup(_credential(master_pwd), **kw)

    @http.route(
        "/web/database/restore",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        max_content_length=None,
    )
    def restore(self, master_pwd=None, **kw):
        return super().restore(_credential(master_pwd), **kw)

    @http.route(
        "/web/database/change_password",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def change_password(self, **kw):
        raise NotFound()
