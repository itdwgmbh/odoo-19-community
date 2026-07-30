# Part of the IT-DW Odoo Community Build. See LICENSE for details.
import datetime
import logging
import subprocess

import odoo
from odoo import http
from odoo.addons.web.controllers.database import Database
from odoo.http import Response, content_disposition, dispatch_rpc
from odoo.tools.misc import str2bool

_logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024


def _age_recipients():
    value = odoo.tools.config.options.get("age_recipients") or ""
    return value.replace(",", " ").split()


class DatabaseAge(Database):
    @http.route("/web/database/backup", type="http", auth="none", methods=["POST"], csrf=False)
    def backup(self, master_pwd, name, backup_format="zip", filestore=True):
        recipients = _age_recipients()
        filestore = str2bool(filestore)
        if not recipients:
            return super().backup(master_pwd, name, backup_format, filestore)
        insecure = odoo.tools.config.verify_admin_password("admin")
        if insecure and master_pwd:
            dispatch_rpc("db", "change_admin_password", ["admin", master_pwd])
        try:
            odoo.service.db.check_super(master_pwd)
            if name not in http.db_list():
                raise Exception(f"Database {name!r} is not known")
            ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{name}_{ts}.{backup_format}.age"
            headers = [
                ("Content-Type", "application/octet-stream; charset=binary"),
                ("Content-Disposition", content_disposition(filename)),
            ]
            # dump_db returns a real file (zip) or a pipe (dump); both carry a
            # file descriptor age can read as stdin, so the dump streams
            # through age without buffering in memory.
            dump_stream = odoo.service.db.dump_db(name, None, backup_format, filestore)
            cmd = ["age", "--encrypt"]
            for recipient in recipients:
                cmd += ["--recipient", recipient]
            proc = subprocess.Popen(cmd, stdin=dump_stream, stdout=subprocess.PIPE)

            def generate():
                try:
                    while chunk := proc.stdout.read(CHUNK_SIZE):
                        yield chunk
                finally:
                    proc.stdout.close()
                    dump_stream.close()
                    rc = proc.wait()
                # Raising aborts the chunked response mid-stream, so the
                # client's download fails loudly instead of storing a
                # truncated file.
                if rc != 0:
                    _logger.error("age exited with code %s", rc)
                    raise RuntimeError(f"age exited with code {rc}")

            return Response(generate(), headers=headers, direct_passthrough=True)
        except Exception as e:
            _logger.exception("Database.backup")
            error = "Database backup error: %s" % (str(e) or repr(e))
            return self._render_template(error=error)
