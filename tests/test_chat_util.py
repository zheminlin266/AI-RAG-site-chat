from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from fastapi import Request
    from backend import chat_util
except ModuleNotFoundError:  # Allows stdlib-only checks before app deps are installed.
    Request = None
    chat_util = None


def make_request(
    *,
    origin: str | None = None,
    host: str = "api.example.test:8000",
    scheme: str = "http",
    client_host: str = "198.51.100.7",
    forwarded_for: str | None = None,
    forwarded_proto: str | None = None,
) -> Request:
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if forwarded_proto is not None:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "scheme": scheme,
        "path": "/api/chat",
        "raw_path": b"/api/chat",
        "query_string": b"",
        "headers": headers,
        "client": (client_host, 12345),
        "server": ("api.example.test", 8000),
    }
    return Request(scope)


@unittest.skipIf(chat_util is None, "FastAPI dependencies are not installed")
class OriginAndProxyTests(unittest.TestCase):
    def test_origin_requires_matching_scheme_host_and_port(self) -> None:
        request = make_request(origin="http://api.example.test:8000")
        self.assertTrue(chat_util.is_allowed_origin(request))
        self.assertFalse(
            chat_util.is_allowed_origin(make_request(origin="https://api.example.test:8000"))
        )
        self.assertFalse(
            chat_util.is_allowed_origin(make_request(origin="http://api.example.test:9000"))
        )

    def test_configured_cross_origin_is_exact(self) -> None:
        with patch.object(chat_util, "CORS_ORIGINS", ("https://site.example.test",)):
            self.assertTrue(
                chat_util.is_allowed_origin(
                    make_request(origin="https://site.example.test")
                )
            )
            self.assertFalse(
                chat_util.is_allowed_origin(
                    make_request(origin="http://site.example.test")
                )
            )

    def test_forwarded_for_requires_a_trusted_direct_proxy(self) -> None:
        request = make_request(forwarded_for="203.0.113.10")
        self.assertEqual(chat_util.client_ip(request), "198.51.100.7")
        with patch.object(chat_util, "TRUSTED_PROXY_IPS", ("198.51.100.0/24",)):
            self.assertEqual(chat_util.client_ip(request), "203.0.113.10")

    def test_trusted_proxy_uses_the_rightmost_forwarded_address(self) -> None:
        request = make_request(forwarded_for="203.0.113.99, 203.0.113.10")
        with patch.object(chat_util, "TRUSTED_PROXY_IPS", ("198.51.100.0/24",)):
            self.assertEqual(chat_util.client_ip(request), "203.0.113.10")

    def test_history_limit_does_not_start_with_an_assistant_reply(self) -> None:
        history = [
            {"role": "user", "content": str(index)}
            if index % 2 == 0
            else {"role": "assistant", "content": str(index)}
            for index in range(41)
        ]
        bounded = chat_util.sanitize(history)
        self.assertEqual(len(bounded), 39)
        self.assertEqual(bounded[0]["role"], "user")

    def test_trusted_proxy_can_preserve_the_external_https_origin(self) -> None:
        request = make_request(
            origin="https://api.example.test",
            host="api.example.test",
            scheme="http",
            client_host="198.51.100.7",
            forwarded_proto="https",
        )
        self.assertFalse(chat_util.is_allowed_origin(request))
        with patch.object(chat_util, "TRUSTED_PROXY_IPS", ("198.51.100.0/24",)):
            self.assertTrue(chat_util.is_allowed_origin(request))
