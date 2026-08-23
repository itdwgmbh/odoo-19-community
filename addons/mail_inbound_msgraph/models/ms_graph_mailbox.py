import logging
from urllib.parse import quote, urlencode

from odoo import models

_logger = logging.getLogger(__name__)

# Graph accepts $top up to 1000. 50 keeps each response small, so a transient
# failure costs one page instead of a whole mailbox listing.
_PAGE_SIZE = 50
# Pages walked per call, so a backlogged mailbox cannot occupy a cron worker
# indefinitely. The remainder is picked up by the next call.
_MAX_PAGES = 20
# Enough to decide whether a message is worth fetching in full, without
# pulling bodies and attachment payloads into the listing response.
_LIST_SELECT = (
    "id,internetMessageId,subject,from,receivedDateTime,hasAttachments,isRead"
)
# Same reasoning for attachments: metadata only, contentBytes on demand.
_ATTACHMENT_SELECT = "id,name,contentType,size,isInline"


class MsGraphMailbox(models.AbstractModel):
    """Read side of Microsoft Graph mail, for other addons to build on.

    Every method takes the mailbox UPN first and returns ``(True, value)`` or
    ``(False, error_message)``, matching ``ms.graph.service._graph_request``.
    Failures are already logged there, so this layer only logs what the
    request layer cannot see: partial or truncated listings, and ingestion.

    Nothing is configured or scheduled here. Consumers own their mailbox
    configuration, their cron, and the decision of what to do with a message
    once it has been processed.
    """

    _name = "ms.graph.mailbox"
    _description = "Microsoft Graph mailbox reader"

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _request(self, method, path, json_data=None, raw=False):
        return self.env["ms.graph.service"]._graph_request(
            method, path, json_data=json_data, raw=raw
        )

    def _query(self, params):
        """Encode OData parameters, leaving `$` and `,` readable in logs."""
        return urlencode(params, safe="$,", quote_via=quote)

    def _folder_path(self, upn, folder=None):
        """`folder` is a well-known name ("inbox", "archive", …) or a folder
        id; None addresses the whole mailbox."""
        path = f"/users/{quote(upn, safe='')}"
        if folder:
            path += f"/mailFolders/{quote(folder, safe='')}"
        return path

    def _message_path(self, upn, message_id):
        return f"/users/{quote(upn, safe='')}/messages/{quote(message_id, safe='')}"

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def _list_messages(
        self,
        upn,
        folder="inbox",
        unread_only=False,
        filter_=None,
        order=None,
        select=_LIST_SELECT,
        page_size=_PAGE_SIZE,
        max_pages=_MAX_PAGES,
    ):
        """List messages in `folder`, following @odata.nextLink.

        `filter_` is an OData expression combined with `unread_only` using
        `and`. Graph rejects a `$filter` and `$orderby` on different
        properties, so pass at most one of the two.

        Returns (True, [message dicts]). A failure on the first page returns
        (False, error); a failure on a later page returns the messages
        already collected, so the remainder is picked up on the next call.
        """
        params = {"$top": page_size}
        if select:
            params["$select"] = select
        filters = []
        if unread_only:
            filters.append("isRead eq false")
        if filter_:
            filters.append(filter_)
        if filters:
            params["$filter"] = " and ".join(filters)
        if order:
            params["$orderby"] = order

        base = self._folder_path(upn, folder)
        path = f"{base}/messages?{self._query(params)}"
        messages = []
        pages = 0
        while path and pages < max_pages:
            ok, body = self._request("GET", path)
            if not ok:
                if not messages:
                    return False, body
                _logger.warning(
                    "ms_graph_inbound_list_partial",
                    extra={
                        "event": "ms_graph_inbound_list_partial",
                        "mailbox": upn,
                        "folder": folder,
                        "collected": len(messages),
                        "error": body,
                    },
                )
                return True, messages
            messages.extend(body.get("value") or [])
            path = body.get("@odata.nextLink")
            pages += 1
        if path:
            _logger.info(
                "ms_graph_inbound_list_truncated",
                extra={
                    "event": "ms_graph_inbound_list_truncated",
                    "mailbox": upn,
                    "folder": folder,
                    "collected": len(messages),
                    "max_pages": max_pages,
                },
            )
        return True, messages

    def _delta_messages(
        self,
        upn,
        folder="inbox",
        delta_link=None,
        select=_LIST_SELECT,
        page_size=_PAGE_SIZE,
        max_pages=_MAX_PAGES,
    ):
        """Incremental change feed for one folder.

        Omit `delta_link` for the first round, which walks the whole folder;
        afterwards pass back the `link` returned by the previous call.

        Returns (True, {"messages": [...], "removed_ids": [...], "link": str,
        "complete": bool}). Store `link` and hand it back next time: it
        resumes the round when `complete` is False and opens the next round
        when True.

        Graph reports an @removed entry when a message is deleted *or* moved
        out of the folder, and re-reports messages on unrelated changes such
        as read-state flips, so consumers must deduplicate themselves —
        `internetMessageId` is the stable key across folders.
        """
        if delta_link:
            path = delta_link
        else:
            params = {"$top": page_size}
            if select:
                params["$select"] = select
            base = self._folder_path(upn, folder)
            path = f"{base}/messages/delta?{self._query(params)}"

        messages = []
        removed_ids = []
        pages = 0
        while pages < max_pages:
            ok, body = self._request("GET", path)
            if not ok:
                if not (messages or removed_ids):
                    return False, body
                _logger.warning(
                    "ms_graph_inbound_delta_partial",
                    extra={
                        "event": "ms_graph_inbound_delta_partial",
                        "mailbox": upn,
                        "folder": folder,
                        "collected": len(messages),
                        "error": body,
                    },
                )
                # `path` still points at the page that failed, so the next
                # call retries it. Already-returned changes are replayed —
                # delta guarantees at-least-once, never exactly-once.
                break
            for item in body.get("value") or []:
                if "@removed" in item:
                    if item.get("id"):
                        removed_ids.append(item["id"])
                else:
                    messages.append(item)
            delta_next = body.get("@odata.deltaLink")
            if delta_next:
                return True, {
                    "messages": messages,
                    "removed_ids": removed_ids,
                    "link": delta_next,
                    "complete": True,
                }
            path = body.get("@odata.nextLink")
            pages += 1
            if not path:
                # Neither link present: nothing more to read and no token to
                # resume from, so the caller must restart from scratch.
                break
        return True, {
            "messages": messages,
            "removed_ids": removed_ids,
            "link": path,
            "complete": False,
        }

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _get_message(self, upn, message_id, select=None):
        """Fetch one message as a Graph JSON object."""
        path = self._message_path(upn, message_id)
        if select:
            path += f"?{self._query({'$select': select})}"
        return self._request("GET", path)

    def _fetch_mime(self, upn, message_id):
        """Fetch one message as raw RFC822 bytes, ready for `_ingest_message`."""
        return self._request(
            "GET", f"{self._message_path(upn, message_id)}/$value", raw=True
        )

    def _list_attachments(self, upn, message_id, select=_ATTACHMENT_SELECT):
        """List attachment metadata. Returns (True, [attachment dicts]).

        Payloads are left out: fetch them individually with
        `_fetch_attachment`, or take the whole message via `_fetch_mime`.
        """
        path = f"{self._message_path(upn, message_id)}/attachments"
        if select:
            path += f"?{self._query({'$select': select})}"
        ok, body = self._request("GET", path)
        if not ok:
            return False, body
        return True, body.get("value") or []

    def _fetch_attachment(self, upn, message_id, attachment_id):
        """Fetch one attachment's raw bytes."""
        path = (
            f"{self._message_path(upn, message_id)}"
            f"/attachments/{quote(attachment_id, safe='')}/$value"
        )
        return self._request("GET", path, raw=True)

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def _find_folder(self, upn, display_name, parent="msgfolderroot"):
        """Resolve a folder display name to its id among `parent`'s children.

        Only direct children are searched — walk the tree with repeated calls
        for nested folders. Well-known names ("inbox", "archive", "sentitems",
        …) need no lookup at all; pass them straight to `folder` or
        `destination`.

        Returns (True, folder_id), or (True, None) when nothing matches.
        """
        escaped = display_name.replace("'", "''")
        params = {
            "$filter": f"displayName eq '{escaped}'",
            "$select": "id,displayName",
            "$top": 1,
        }
        base = self._folder_path(upn, parent)
        ok, body = self._request("GET", f"{base}/childFolders?{self._query(params)}")
        if not ok:
            return False, body
        found = body.get("value") or []
        return True, (found[0].get("id") if found else None)

    # ------------------------------------------------------------------
    # Post-processing actions
    # ------------------------------------------------------------------

    def _mark_read(self, upn, message_id, read=True):
        """Flip the message's read state. Returns (True, updated message)."""
        return self._request(
            "PATCH",
            self._message_path(upn, message_id),
            json_data={"isRead": bool(read)},
        )

    def _move_message(self, upn, message_id, destination):
        """Move a message to `destination` (well-known name or folder id).

        Graph implements the move as copy-then-remove, so the message gets a
        new id and `message_id` is dead afterwards. Returns (True, new_id).
        """
        ok, body = self._request(
            "POST",
            f"{self._message_path(upn, message_id)}/move",
            json_data={"destinationId": destination},
        )
        if not ok:
            return False, body
        return True, (body or {}).get("id")

    def _delete_message(self, upn, message_id):
        """Delete a message to Deleted Items. Returns (True, {}).

        This is Graph's soft delete; it has a separate permanentDelete action
        for hard deletion, which this addon deliberately does not expose.
        """
        return self._request("DELETE", self._message_path(upn, message_id))

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _ingest_message(
        self,
        mime,
        model=None,
        custom_values=None,
        thread_id=None,
        save_original=False,
        strip_attachments=False,
    ):
        """Hand raw RFC822 bytes to Odoo's mail gateway.

        `mail.thread.message_process` routes on aliases, References and
        In-Reply-To first and only falls back to `model`; it also ignores any
        message whose Message-Id already exists in mail.message, which makes
        re-delivery from a delta round harmless.

        Runs inside a savepoint so a rejected message leaves the caller's
        transaction usable — the caller decides whether to leave the message
        in the mailbox for a retry.

        Returns (True, thread_id) on success, (True, False) when Odoo ignored
        the message as a duplicate or bounce loop, and (False, error) when
        routing or parsing failed.
        """
        try:
            with self.env.cr.savepoint():
                routed_id = self.env["mail.thread"].message_process(
                    model,
                    mime,
                    custom_values=custom_values,
                    save_original=save_original,
                    strip_attachments=strip_attachments,
                    thread_id=thread_id,
                )
        except Exception as e:
            _logger.warning(
                "ms_graph_inbound_ingest_failed",
                extra={
                    "event": "ms_graph_inbound_ingest_failed",
                    "model": model,
                    "error": str(e),
                },
            )
            return False, str(e)
        return True, routed_id or False
