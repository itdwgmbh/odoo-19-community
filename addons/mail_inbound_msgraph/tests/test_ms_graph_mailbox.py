from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

GRAPH = "https://graph.microsoft.com/v1.0"


def _msg(msg_id, **kw):
    return dict({"id": msg_id, "subject": f"subject {msg_id}"}, **kw)


@tagged("post_install", "-at_install")
class TestMsGraphMailbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mailbox = cls.env["ms.graph.mailbox"]
        cls.upn = "invoices@example.com"

    def _patch_graph(self, *responses):
        """Patch ms.graph.service._graph_request with a canned response queue."""
        queue = iter(responses)
        return patch.object(
            type(self.env["ms.graph.service"]),
            "_graph_request",
            side_effect=lambda *a, **kw: next(queue),
        )

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def test_list_builds_folder_scoped_path(self):
        with self._patch_graph((True, {"value": [_msg("a")]})) as graph:
            ok, messages = self.mailbox._list_messages(self.upn)
        self.assertTrue(ok)
        self.assertEqual([m["id"] for m in messages], ["a"])
        method, path = graph.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertTrue(
            path.startswith(
                "/users/invoices%40example.com/mailFolders/inbox/messages?"
            ),
            path,
        )
        self.assertIn("$top=50", path)
        self.assertIn("$select=id,internetMessageId", path)

    def test_list_without_folder_covers_whole_mailbox(self):
        with self._patch_graph((True, {"value": []})) as graph:
            self.mailbox._list_messages(self.upn, folder=None)
        path = graph.call_args.args[1]
        self.assertNotIn("mailFolders", path)
        self.assertTrue(
            path.startswith("/users/invoices%40example.com/messages?"), path
        )

    def test_list_combines_unread_and_custom_filter(self):
        with self._patch_graph((True, {"value": []})) as graph:
            self.mailbox._list_messages(
                self.upn, unread_only=True, filter_="hasAttachments eq true"
            )
        path = graph.call_args.args[1]
        self.assertIn(
            "$filter=isRead%20eq%20false%20and%20hasAttachments%20eq%20true", path
        )

    def test_list_follows_next_link(self):
        page1 = (
            True,
            {"value": [_msg("a")], "@odata.nextLink": f"{GRAPH}/next-page"},
        )
        page2 = (True, {"value": [_msg("b")]})
        with self._patch_graph(page1, page2) as graph:
            ok, messages = self.mailbox._list_messages(self.upn)
        self.assertTrue(ok)
        self.assertEqual([m["id"] for m in messages], ["a", "b"])
        self.assertEqual(graph.call_args_list[1].args[1], f"{GRAPH}/next-page")

    def test_list_first_page_failure_is_reported(self):
        with self._patch_graph((False, "Mailbox not found")):
            ok, error = self.mailbox._list_messages(self.upn)
        self.assertFalse(ok)
        self.assertEqual(error, "Mailbox not found")

    def test_list_later_page_failure_keeps_collected_messages(self):
        page1 = (
            True,
            {"value": [_msg("a")], "@odata.nextLink": f"{GRAPH}/next-page"},
        )
        with self._patch_graph(page1, (False, "throttled")):
            ok, messages = self.mailbox._list_messages(self.upn)
        self.assertTrue(ok)
        self.assertEqual([m["id"] for m in messages], ["a"])

    def test_list_stops_at_max_pages(self):
        page = (True, {"value": [_msg("a")], "@odata.nextLink": f"{GRAPH}/next-page"})
        with self._patch_graph(page, page, page) as graph:
            ok, messages = self.mailbox._list_messages(self.upn, max_pages=2)
        self.assertTrue(ok)
        self.assertEqual(graph.call_count, 2)
        self.assertEqual(len(messages), 2)

    # ------------------------------------------------------------------
    # Delta
    # ------------------------------------------------------------------

    def test_delta_first_round_returns_delta_link(self):
        body = {
            "value": [
                _msg("a"),
                {"id": "gone", "@removed": {"reason": "deleted"}},
            ],
            "@odata.deltaLink": f"{GRAPH}/delta?$deltatoken=T1",
        }
        with self._patch_graph((True, body)) as graph:
            ok, result = self.mailbox._delta_messages(self.upn)
        self.assertTrue(ok)
        self.assertEqual([m["id"] for m in result["messages"]], ["a"])
        self.assertEqual(result["removed_ids"], ["gone"])
        self.assertEqual(result["link"], f"{GRAPH}/delta?$deltatoken=T1")
        self.assertTrue(result["complete"])
        path = graph.call_args.args[1]
        self.assertTrue(
            path.startswith(
                "/users/invoices%40example.com/mailFolders/inbox/messages/delta?"
            ),
            path,
        )

    def test_delta_reuses_stored_link_verbatim(self):
        stored = f"{GRAPH}/delta?$deltatoken=T1"
        with self._patch_graph(
            (True, {"value": [], "@odata.deltaLink": stored})
        ) as graph:
            self.mailbox._delta_messages(self.upn, delta_link=stored)
        self.assertEqual(graph.call_args.args[1], stored)

    def test_delta_incomplete_round_returns_resume_link(self):
        page = (
            True,
            {"value": [_msg("a")], "@odata.nextLink": f"{GRAPH}/delta?$skiptoken=S1"},
        )
        with self._patch_graph(page):
            ok, result = self.mailbox._delta_messages(self.upn, max_pages=1)
        self.assertTrue(ok)
        self.assertFalse(result["complete"])
        self.assertEqual(result["link"], f"{GRAPH}/delta?$skiptoken=S1")

    def test_delta_first_page_failure_is_reported(self):
        with self._patch_graph((False, "invalid delta token")):
            ok, error = self.mailbox._delta_messages(self.upn, delta_link="stale")
        self.assertFalse(ok)
        self.assertEqual(error, "invalid delta token")

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def test_fetch_mime_requests_raw_value(self):
        with self._patch_graph((True, b"MIME-Version: 1.0")) as graph:
            ok, mime = self.mailbox._fetch_mime(self.upn, "AAMk=")
        self.assertTrue(ok)
        self.assertEqual(mime, b"MIME-Version: 1.0")
        self.assertEqual(
            graph.call_args.args[1],
            "/users/invoices%40example.com/messages/AAMk%3D/$value",
        )
        self.assertTrue(graph.call_args.kwargs["raw"])

    def test_list_attachments_returns_metadata_only(self):
        body = {"value": [{"id": "att1", "name": "invoice.pdf", "size": 1234}]}
        with self._patch_graph((True, body)) as graph:
            ok, attachments = self.mailbox._list_attachments(self.upn, "AAMk=")
        self.assertTrue(ok)
        self.assertEqual(attachments[0]["name"], "invoice.pdf")
        path = graph.call_args.args[1]
        self.assertIn("/messages/AAMk%3D/attachments?", path)
        self.assertIn("$select=id,name,contentType,size,isInline", path)

    def test_fetch_attachment_requests_raw_value(self):
        with self._patch_graph((True, b"%PDF-1.4")) as graph:
            ok, payload = self.mailbox._fetch_attachment(self.upn, "AAMk=", "att1")
        self.assertTrue(ok)
        self.assertEqual(payload, b"%PDF-1.4")
        self.assertEqual(
            graph.call_args.args[1],
            "/users/invoices%40example.com/messages/AAMk%3D/attachments/att1/$value",
        )
        self.assertTrue(graph.call_args.kwargs["raw"])

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def test_find_folder_returns_id(self):
        with self._patch_graph((True, {"value": [{"id": "F1"}]})) as graph:
            ok, folder_id = self.mailbox._find_folder(self.upn, "Processed")
        self.assertTrue(ok)
        self.assertEqual(folder_id, "F1")
        path = graph.call_args.args[1]
        self.assertIn("/mailFolders/msgfolderroot/childFolders?", path)
        self.assertIn("displayName%20eq%20%27Processed%27", path)

    def test_find_folder_escapes_quotes(self):
        with self._patch_graph((True, {"value": []})) as graph:
            ok, folder_id = self.mailbox._find_folder(self.upn, "Dan's mail")
        self.assertTrue(ok)
        self.assertIsNone(folder_id)
        self.assertIn("Dan%27%27s", graph.call_args.args[1])

    # ------------------------------------------------------------------
    # Post-processing actions
    # ------------------------------------------------------------------

    def test_mark_read_patches_is_read(self):
        with self._patch_graph((True, {"id": "AAMk=", "isRead": True})) as graph:
            ok, _body = self.mailbox._mark_read(self.upn, "AAMk=")
        self.assertTrue(ok)
        method, path = graph.call_args.args[:2]
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "/users/invoices%40example.com/messages/AAMk%3D")
        self.assertEqual(graph.call_args.kwargs["json_data"], {"isRead": True})

    def test_move_returns_new_message_id(self):
        with self._patch_graph((True, {"id": "NEWID"})) as graph:
            ok, new_id = self.mailbox._move_message(self.upn, "AAMk=", "archive")
        self.assertTrue(ok)
        self.assertEqual(new_id, "NEWID")
        method, path = graph.call_args.args[:2]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/users/invoices%40example.com/messages/AAMk%3D/move")
        self.assertEqual(
            graph.call_args.kwargs["json_data"], {"destinationId": "archive"}
        )

    def test_move_failure_returns_error(self):
        with self._patch_graph((False, "ErrorItemNotFound")):
            ok, error = self.mailbox._move_message(self.upn, "AAMk=", "archive")
        self.assertFalse(ok)
        self.assertEqual(error, "ErrorItemNotFound")

    def test_delete_uses_delete_verb(self):
        with self._patch_graph((True, {})) as graph:
            ok, _body = self.mailbox._delete_message(self.upn, "AAMk=")
        self.assertTrue(ok)
        method, path = graph.call_args.args[:2]
        self.assertEqual(method, "DELETE")
        self.assertEqual(path, "/users/invoices%40example.com/messages/AAMk%3D")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def test_ingest_delegates_to_mail_gateway(self):
        mime = b"Subject: hi\r\n\r\nbody"
        with patch.object(
            type(self.env["mail.thread"]), "message_process", return_value=42
        ) as process:
            ok, thread_id = self.mailbox._ingest_message(mime, model="mail.channel")
        self.assertTrue(ok)
        self.assertEqual(thread_id, 42)
        self.assertEqual(process.call_args.args, ("mail.channel", mime))

    def test_ingest_reports_ignored_message(self):
        with patch.object(
            type(self.env["mail.thread"]), "message_process", return_value=False
        ):
            ok, thread_id = self.mailbox._ingest_message(b"raw")
        self.assertTrue(ok)
        self.assertFalse(thread_id)

    def test_ingest_returns_error_instead_of_raising(self):
        with patch.object(
            type(self.env["mail.thread"]),
            "message_process",
            side_effect=ValueError("No possible route found"),
        ):
            ok, error = self.mailbox._ingest_message(b"raw")
        self.assertFalse(ok)
        self.assertIn("No possible route found", error)
        # The savepoint rolled back cleanly, so the cursor is still usable.
        self.assertTrue(self.env["res.users"].search_count([]) > 0)
