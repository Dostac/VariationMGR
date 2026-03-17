import json
import socket
from urllib import error, request


DISCOVERY_MAGIC = "VB_BATCH_DISCOVER_V1"


def normalize_server_url(server_url):
    url = (server_url or "").strip()
    if not url:
        return ""
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url
    return url.rstrip("/")


def request_json(method, url, payload=None, timeout=5.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def check_health(server_url, timeout=4.0):
    base = normalize_server_url(server_url)
    if not base:
        raise RuntimeError("Server URL is empty.")
    return request_json("GET", f"{base}/health", timeout=timeout)


def submit_job(server_url, job_request, timeout=8.0):
    base = normalize_server_url(server_url)
    if not base:
        raise RuntimeError("Server URL is empty.")
    return request_json("POST", f"{base}/submit", payload=job_request, timeout=timeout)


# Backward compatibility aliases for existing internal callers.
_normalize_server_url = normalize_server_url
_request_json = request_json


def discover_server(discovery_port=8766, timeout=2.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(DISCOVERY_MAGIC.encode("utf-8"), ("255.255.255.255", int(discovery_port)))
        # Single-shot discovery: returns the first valid responder.
        # Multi-server environments should use a dedicated enumeration method.
        data, _addr = sock.recvfrom(4096)
        payload = json.loads(data.decode("utf-8", errors="ignore"))
        host = str(payload.get("http_host", "")).strip()
        port = int(payload.get("http_port", 0))
        if host and port > 0:
            return f"http://{host}:{port}"
    except Exception:
        return ""
    finally:
        sock.close()
    return ""
