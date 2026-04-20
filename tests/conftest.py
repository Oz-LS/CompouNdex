"""
Test configuration.

Adds the project root to sys.path so `from services import ...` works when
pytest is run from the repo root, and provides a shared Flask app fixture
with an in-memory SQLite DB for tests that need an application context.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def app():
    """Flask app bound to an in-memory SQLite DB."""
    os.environ["FLASK_ENV"] = "development"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    # Reimport lazily so env vars above take effect.
    from app import create_app
    from extensions import db

    flask_app = create_app("development")
    # WTF_CSRF_ENABLED off so tests can post without tokens.
    flask_app.config["WTF_CSRF_ENABLED"] = False
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        from sqlalchemy import event
        engine = db.engine

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        # Force a reconnect so the listener fires for the test connection.
        engine.dispose()

        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
