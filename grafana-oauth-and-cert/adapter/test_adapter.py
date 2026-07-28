#!/usr/bin/python3
import http.client
import json
import threading
import unittest

from adapter import (
    AdapterError,
    ThreadingHTTPServer,
    UserInfoHandler,
    normalize_discord_user,
)


VALID_USER = {
    "id": "DISCORD_ADMIN_USER_ID",
    "username": "grafana-admin-user",
    "email": "user@example.invalid",
    "verified": True,
}


class NormalizeTests(unittest.TestCase):
    def test_adds_sub_from_discord_id(self):
        result = normalize_discord_user(VALID_USER)
        self.assertEqual(result["sub"], VALID_USER["id"])
        self.assertEqual(result["id"], VALID_USER["id"])
        self.assertEqual(result["username"], VALID_USER["username"])

    def test_overwrites_untrusted_sub(self):
        payload = dict(VALID_USER, sub="wrong")
        result = normalize_discord_user(payload)
        self.assertEqual(result["sub"], VALID_USER["id"])

    def test_rejects_missing_required_field(self):
        for field in ("id", "username", "email"):
            with self.subTest(field=field):
                payload = dict(VALID_USER)
                payload.pop(field)
                with self.assertRaises(AdapterError):
                    normalize_discord_user(payload)

    def test_rejects_unverified_email(self):
        with self.assertRaises(AdapterError):
            normalize_discord_user(dict(VALID_USER, verified=False))

    def test_rejects_non_object(self):
        with self.assertRaises(AdapterError):
            normalize_discord_user([])


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.seen_authorization = []
        seen = self.seen_authorization

        class TestHandler(UserInfoHandler):
            fetcher = staticmethod(
                lambda authorization: (
                    seen.append(authorization)
                    or normalize_discord_user(VALID_USER)
                )
            )

        self.handler_class = TestHandler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def request(self, method="GET", path="/userinfo", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_port,
            timeout=2,
        )
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, response.getheaders(), body

    def test_success_returns_normalized_profile(self):
        status, headers, body = self.request(
            headers={"Authorization": "Bearer test-token"}
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["sub"], VALID_USER["id"])
        self.assertEqual(payload["id"], VALID_USER["id"])
        self.assertEqual(
            self.seen_authorization,
            ["Bearer test-token"],
        )
        self.assertIn(("Cache-Control", "no-store"), headers)

    def test_missing_authorization_is_rejected(self):
        status, _, body = self.request()
        self.assertEqual(status, 401)
        self.assertEqual(
            json.loads(body)["error"],
            "missing_bearer_token",
        )
        self.assertEqual(self.seen_authorization, [])

    def test_wrong_path_is_rejected(self):
        status, _, _ = self.request(
            path="/other",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.seen_authorization, [])

    def test_non_get_method_is_rejected(self):
        status, _, _ = self.request(
            method="POST",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 405)
        self.assertEqual(self.seen_authorization, [])

    def test_upstream_failure_is_fail_closed(self):
        self.handler_class.fetcher = staticmethod(
            lambda _authorization: (_ for _ in ()).throw(
                AdapterError("simulated failure")
            )
        )
        status, _, body = self.request(
            headers={"Authorization": "Bearer test-token"}
        )
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(body)["error"],
            "upstream_userinfo_failed",
        )


if __name__ == "__main__":
    unittest.main()
