import unittest

from proxy_utils import (
    build_playwright_proxy,
    build_requests_proxy,
    parse_proxy,
)


class ProxyUtilsTests(unittest.TestCase):
    def test_parses_socks5_host_port_user_password(self):
        parsed = parse_proxy(
            "socks5://us.cliproxy.io:3010:user-name:secret"
        )
        self.assertEqual(
            parsed,
            {
                "scheme": "socks5",
                "host": "us.cliproxy.io",
                "port": "3010",
                "username": "user-name",
                "password": "secret",
            },
        )

    def test_builds_playwright_socks5_settings(self):
        self.assertEqual(
            build_playwright_proxy(
                "socks5://us.cliproxy.io:3010:user-name:secret"
            ),
            {
                "server": "socks5://user-name:secret@us.cliproxy.io:3010",
                "bypass": "localhost",
            },
        )

    def test_builds_requests_socks5h_url(self):
        self.assertEqual(
            build_requests_proxy(
                "socks5://us.cliproxy.io:3010:user-name:secret"
            ),
            "socks5h://user-name:secret@us.cliproxy.io:3010",
        )

    def test_keeps_legacy_http_proxy_compatible(self):
        self.assertEqual(
            build_playwright_proxy(
                "http://us.cliproxy.io:3010:user-name:secret"
            )["server"],
            "http://us.cliproxy.io:3010",
        )
