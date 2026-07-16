import datetime
import secrets

from flask.json.tag import TaggedJSONSerializer
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

from app.models import Session as SessionModel


class ServerSideSession(CallbackDict, SessionMixin):
    """A session whose contents live in the database, not the cookie."""

    def __init__(self, initial=None, sid=None, new=False):
        def on_update(self):
            self.modified = True

        super().__init__(initial, on_update)
        self.sid = sid
        self.new = new
        self.modified = False


class PeeweeSessionInterface(SessionInterface):
    """Store session data in the ``Session`` table; keep only the sid in the cookie."""

    serializer = TaggedJSONSerializer()
    session_class = ServerSideSession

    def _new_session(self):
        return self.session_class(sid=secrets.token_urlsafe(32), new=True)

    def open_session(self, app, request):
        sid = request.cookies.get(app.config["SESSION_COOKIE_NAME"])
        if not sid:
            return self._new_session()

        record = SessionModel.get_or_none(SessionModel.sid == sid)
        if record is None:
            return self._new_session()

        if record.expiry is not None and record.expiry < datetime.datetime.now():
            record.delete_instance()
            return self._new_session()

        data = self.serializer.loads(record.data)
        return self.session_class(data, sid=sid)

    def save_session(self, app, session, response):
        name = app.config["SESSION_COOKIE_NAME"]
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        # Empty session (e.g. after logout): drop the row and the cookie.
        if not session:
            if session.modified:
                SessionModel.delete().where(SessionModel.sid == session.sid).execute()
                response.delete_cookie(name, domain=domain, path=path)
            return

        if not self.should_set_cookie(app, session):
            return

        expiry = self.get_expiration_time(app, session)
        data = self.serializer.dumps(dict(session))

        record = SessionModel.get_or_none(SessionModel.sid == session.sid)
        if record is None:
            SessionModel.create(sid=session.sid, data=data, expiry=expiry)
        else:
            record.data = data
            record.expiry = expiry
            record.save()

        response.set_cookie(
            name,
            session.sid,
            expires=expiry,
            httponly=self.get_cookie_httponly(app),
            domain=domain,
            path=path,
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
        )
