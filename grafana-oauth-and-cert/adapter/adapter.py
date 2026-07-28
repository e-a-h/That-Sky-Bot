#!/usr/bin/python3
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BIND_HOST = "127.0.0.1"
BIND_PORT = 9080
DISCORD_USERINFO_URL = "https://discord.com/api/v10/users/@me"
MAX_RESPONSE_BYTES = 65536
UPSTREAM_TIMEOUT_SECONDS = 5
BEARER_PATTERN = re.compile(r"^Bearer [^\s]+$")


class AdapterError(Exception):
    pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def normalize_discord_user(payload):
    if not isinstance(payload, dict):
        raise AdapterError("Discord UserInfo was not an object")

    for field in ("id", "username", "email"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"Discord UserInfo lacked {field}")

    if payload.get("verified") is not True:
        raise AdapterError("Discord email was not verified")

    normalized = dict(payload)
    normalized["sub"] = payload["id"]
    return normalized


def fetch_discord_user(authorization):
    if not BEARER_PATTERN.fullmatch(authorization):
        raise AdapterError("Missing or invalid bearer token")

    request = Request(
        DISCORD_USERINFO_URL,
        headers={
            "Accept": "application/json",
            "Authorization": authorization,
            "User-Agent": "grafana-discord-userinfo/1.0",
        },
        method="GET",
    )

    try:
        with urlopen(
            request,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        ) as response:
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if content_type != "application/json":
                raise AdapterError(
                    "Discord UserInfo was not JSON"
                )
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise AdapterError("Discord UserInfo request failed") from error

    if len(body) > MAX_RESPONSE_BYTES:
        raise AdapterError("Discord UserInfo response was too large")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterError("Discord UserInfo JSON was invalid") from error

    return normalize_discord_user(payload)


class UserInfoHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "grafana-discord-userinfo"
    sys_version = ""
    fetcher = staticmethod(fetch_discord_user)

    def log_message(self, _format, *_args):
        return

    def send_json(self, status, payload):
        body = json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/userinfo":
            self.send_json(404, {"error": "not_found"})
            return

        authorization = self.headers.get("Authorization", "")
        if not BEARER_PATTERN.fullmatch(authorization):
            self.send_json(
                401,
                {"error": "missing_bearer_token"},
            )
            return

        try:
            payload = self.fetcher(authorization)
        except AdapterError:
            print(
                "Discord UserInfo request or validation failed",
                file=sys.stderr,
                flush=True,
            )
            self.send_json(
                502,
                {"error": "upstream_userinfo_failed"},
            )
            return
        except Exception as error:
            print(
                "Unexpected UserInfo adapter error: "
                f"{type(error).__name__}",
                file=sys.stderr,
                flush=True,
            )
            self.send_json(
                500,
                {"error": "internal_error"},
            )
            return

        self.send_json(200, payload)

    def method_not_allowed(self):
        self.send_json(405, {"error": "method_not_allowed"})

    do_POST = method_not_allowed
    do_PUT = method_not_allowed
    do_PATCH = method_not_allowed
    do_DELETE = method_not_allowed
    do_HEAD = method_not_allowed


def main():
    server = ThreadingHTTPServer(
        (BIND_HOST, BIND_PORT),
        UserInfoHandler,
    )
    print(
        f"Listening on {BIND_HOST}:{BIND_PORT}",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
