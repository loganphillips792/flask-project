"""The shared chat room: one page, everyone on it is in the same conversation.

Messages travel over a plain WebSocket (flask-sock) and are persisted to the
ChatMessage table, so the room survives restarts. Broadcast is an in-process
set of open sockets — complete only because gunicorn runs a single worker
(already load-bearing for prometheus and SQLite); a second worker would
silently split the room into per-process islands.
"""

import json
import logging
import threading

from flask import Blueprint, g, render_template
from flask_sock import Sock

from app.auth import role_required
from app.database import db
from app.models import ChatMessage, User

logger = logging.getLogger(__name__)

chat = Blueprint("chat", __name__, template_folder="../templates")
sock = Sock()

CHAT_ROLES = ("member", "admin")
MAX_MESSAGE_LEN = 2000
HISTORY_LIMIT = 50

_clients = set()
_lock = threading.Lock()


@chat.get("/chat")
@role_required(*CHAT_ROLES)
def page():
    logger.info(f"user {g.user.email} is viewing the chat")
    # Newest 50 fetched descending, then reversed so the page reads
    # oldest-to-newest with the latest message at the bottom.
    history = list(
        reversed(
            ChatMessage.select(ChatMessage, User)
            .join(User)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_LIMIT)
        )
    )
    return render_template("chat.html", messages=history)


@sock.route("/chat/ws")
def ws_endpoint(ws):
    # flask-sock completes the WebSocket upgrade before this handler runs, so
    # @role_required (which aborts with an HTTP 403) can't gate it — check
    # here and close with an application code the client can distinguish
    # from a network drop, so it knows not to reconnect.
    if g.user is None or not g.user_roles.intersection(CHAT_ROLES):
        ws.close(reason=4403, message="forbidden")
        return
    user = g.user
    with _lock:
        _clients.add(ws)
    try:
        while True:
            raw = ws.receive()
            try:
                body = (json.loads(raw).get("body") or "").strip()
            except (ValueError, AttributeError):
                continue
            body = body[:MAX_MESSAGE_LEN]
            if not body:
                continue
            # This thread outlives the request setup that opened a connection;
            # reopen in case teardown or an earlier error closed it.
            db.connect(reuse_if_open=True)
            message = ChatMessage.create(user=user, body=body)
            _broadcast(
                {
                    "name": user.name,
                    "body": message.body,
                    "created_at": message.created_at.isoformat(),
                }
            )
    finally:
        with _lock:
            _clients.discard(ws)


def _broadcast(payload):
    """Send `payload` to every open socket, dropping any that have died.

    The lock also serializes concurrent broadcasts so two handler threads
    never interleave frames on the same socket.
    """
    data = json.dumps(payload)
    with _lock:
        for client in list(_clients):
            try:
                client.send(data)
            except Exception:
                _clients.discard(client)
