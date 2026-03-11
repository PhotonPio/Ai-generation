from __future__ import annotations

import json
import mimetypes
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server


_thread_local = threading.local()


@dataclass
class _Request:
    body: bytes = b""
    headers: dict[str, str] | None = None

    def get_json(self, force: bool = False) -> Any:
        del force
        if not self.body:
            return {}
        return json.loads(self.body.decode("utf-8"))


class _RequestProxy:
    def __getattr__(self, name: str) -> Any:
        req = getattr(_thread_local, "request", None)
        if req is None:
            raise RuntimeError("No active request")
        return getattr(req, name)


request = _RequestProxy()


class Response:
    def __init__(self, body: bytes | str, status_code: int = 200, mimetype: str = "application/json") -> None:
        self.status_code = status_code
        self.mimetype = mimetype
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    @property
    def data(self) -> bytes:
        return self._body

    def get_json(self) -> Any:
        return json.loads(self._body.decode("utf-8"))


class Flask:
    def __init__(self, name: str) -> None:
        self.name = name
        self._routes: list[tuple[str, set[str], Callable[..., Any]]] = []

    def route(self, path: str, methods: list[str] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        allowed = set((methods or ["GET"]))

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._routes.append((path, allowed, fn))
            return fn

        return decorator

    def _match(self, path: str, method: str) -> tuple[Callable[..., Any], dict[str, str]] | None:
        for route, methods, fn in self._routes:
            if method not in methods:
                continue
            if "<" not in route:
                if route == path:
                    return fn, {}
                continue
            r_parts = route.strip("/").split("/")
            p_parts = path.strip("/").split("/")
            if len(r_parts) != len(p_parts):
                continue
            vals: dict[str, str] = {}
            ok = True
            for rp, pp in zip(r_parts, p_parts):
                if rp.startswith("<") and rp.endswith(">"):
                    vals[rp[1:-1]] = pp
                elif rp != pp:
                    ok = False
                    break
            if ok:
                return fn, vals
        return None

    def _to_response(self, rv: Any) -> Response:
        if isinstance(rv, Response):
            return rv
        if isinstance(rv, tuple):
            body, status = rv
            resp = self._to_response(body)
            resp.status_code = status
            return resp
        if isinstance(rv, (dict, list)):
            return jsonify(rv)
        return Response(str(rv), mimetype="text/plain")

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")
        match = self._match(path, method)
        if not match:
            resp = Response(b'{"error":"Not found"}', status_code=404)
        else:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            body = environ["wsgi.input"].read(length) if length > 0 else b""
            _thread_local.request = _Request(body=body, headers={})
            fn, kwargs = match
            try:
                rv = fn(**kwargs)
            finally:
                _thread_local.request = None
            resp = self._to_response(rv)
        status = f"{resp.status_code} {'OK' if resp.status_code < 400 else 'ERROR'}"
        headers = [("Content-Type", resp.mimetype), ("Content-Length", str(len(resp.data)))]
        start_response(status, headers)
        return [resp.data]

    def test_client(self) -> "TestClient":
        return TestClient(self)

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
        del debug
        server = make_server(host, port, self)
        server.serve_forever()


class TestClient:
    def __init__(self, app: Flask) -> None:
        self.app = app

    def _request(self, method: str, path: str, json_body: Any | None = None) -> Response:
        body = b""
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": __import__("io").BytesIO(body),
        }
        payload: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            payload["status"] = int(status.split()[0])
            payload["headers"] = headers

        chunks = self.app(environ, start_response)
        ctype = dict(payload.get("headers", [])).get("Content-Type", "application/json")
        return Response(b"".join(chunks), status_code=payload.get("status", 500), mimetype=ctype)

    def get(self, path: str) -> Response:
        return self._request("GET", path)

    def post(self, path: str, json: Any | None = None) -> Response:
        return self._request("POST", path, json_body=json)


def jsonify(data: Any) -> Response:
    return Response(json.dumps(data), mimetype="application/json")


def send_file(path: str | Path, mimetype: str | None = None, as_attachment: bool = False) -> Response:
    del as_attachment
    p = Path(path)
    data = p.read_bytes()
    ctype = mimetype or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return Response(data, mimetype=ctype)
