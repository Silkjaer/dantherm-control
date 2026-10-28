import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from webui_auth import AuthManager, REMEMBER_SESSION_SECONDS, SHORT_SESSION_SECONDS


def test_remembered_session_survives_auth_manager_restart():
    with tempfile.TemporaryDirectory() as tmp:
        auth_path = Path(tmp) / "auth.json"
        auth = AuthManager(auth_path)
        auth.save("admin", "long-test-password", True)
        sid, csrf = auth.session("admin", remember=True)
        assert auth.session_max_age(sid) == REMEMBER_SESSION_SECONDS
        assert (Path(tmp) / "webui-sessions.json").exists()

        restarted = AuthManager(auth_path)
        session = restarted.authenticate_cookie(f"dantherm_session={sid}")
        assert session is not None
        assert session["username"] == "admin"
        assert session["csrf"] == csrf
        assert session["remember"] is True


def test_short_session_is_not_persisted():
    with tempfile.TemporaryDirectory() as tmp:
        auth_path = Path(tmp) / "auth.json"
        auth = AuthManager(auth_path)
        auth.save("admin", "long-test-password", True)
        sid, _csrf = auth.session("admin", remember=False)
        assert auth.session_max_age(sid) == SHORT_SESSION_SECONDS

        restarted = AuthManager(auth_path)
        assert restarted.authenticate_cookie(f"dantherm_session={sid}") is None


def test_concurrent_requests_with_a_stale_cookie_do_not_fail():
    # The WebUI is a ThreadingHTTPServer: a browser loading a page with an
    # expired cookie makes several requests at once, and each one drops the
    # stale session and rewrites the remembered-session file.
    import threading

    with tempfile.TemporaryDirectory() as tmp:
        auth = AuthManager(Path(tmp) / "auth.json")
        auth.save("admin", "long-test-password", True)
        auth.session("admin", remember=True)
        errors = []

        def request():
            try:
                for _ in range(200):
                    auth.authenticate_cookie("dantherm_session=expired")
            except Exception as error:  # noqa: BLE001 - collected for the assert
                errors.append(error)

        threads = [threading.Thread(target=request) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert not list(Path(tmp).glob("*.tmp"))
