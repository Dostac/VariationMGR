import html as _html
import json
from pathlib import Path

_DIR = Path(__file__).parent

CLIENT_CONFIG = {
    "poll_ms": 3000,
    "csrf_header": "X-VB-Request",
    "csrf_value": "1",
}


def render_dashboard(state, server_address):
    host, port = server_address[0], server_address[1]
    template = (_DIR / "server_dashboard.html").read_text(encoding="utf-8")
    return (template
        .replace("__TITLE__",     _esc(f"VB Batch Server — {host}:{port}"))
        .replace("__HTTP_ADDR__", _esc(f"http://{host}:{port}"))
        .replace("__CFG__",       json.dumps(CLIENT_CONFIG))
    )


def read_stylesheet():
    return (_DIR / "server_dashboard.css").read_text(encoding="utf-8")


def read_js():
    return (_DIR / "server_dashboard.js").read_text(encoding="utf-8")


def render_submitter(server_address):
    """The recipe submitter page (/submitter). Shares the dashboard stylesheet."""
    host, port = server_address[0], server_address[1]
    template = (_DIR / "submitter.html").read_text(encoding="utf-8")
    return (template
        .replace("__TITLE__", _esc(f"Submitter — {host}:{port}"))
        .replace("__CFG__",   json.dumps(CLIENT_CONFIG))
    )


def read_submitter_css():
    return (_DIR / "submitter.css").read_text(encoding="utf-8")


def read_submitter_js():
    return (_DIR / "submitter.js").read_text(encoding="utf-8")


def _esc(value):
    return _html.escape(str(value or ""))
