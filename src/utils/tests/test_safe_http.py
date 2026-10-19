import socket
from unittest import TestCase
from unittest.mock import patch

import httpcore
import httpx

from utils.safe_http import UnsafeAddressError, is_public_address, public_http_client


def _resolves_to(*addresses):
    return [
        (
            socket.AF_INET6 if ":" in a else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (a, 80),
        )
        for a in addresses
    ]


class PublicHttpClientTests(TestCase):
    def setUp(self):
        self.client = public_http_client(timeout=httpx.Timeout(1), headers={})

    def test_refuses_a_host_with_any_non_public_address(self):
        for addresses in (
            ("10.0.0.5",),
            ("93.184.215.14", "169.254.169.254"),
            ("::ffff:127.0.0.1",),
            ("64:ff9b::a9fe:a9fe",),
            ("::a9fe:a9fe",),
        ):
            # Arrange
            with (
                self.subTest(addresses),
                patch("socket.getaddrinfo", return_value=_resolves_to(*addresses)),
                patch.object(httpcore.SyncBackend, "connect_tcp") as connect,
            ):
                # Act / Assert
                with self.assertRaises(UnsafeAddressError):
                    self.client.get("http://intranet.example.org/")
                connect.assert_not_called()

    def test_connects_to_the_address_it_checked(self):
        # Arrange
        with (
            patch("socket.getaddrinfo", return_value=_resolves_to("93.184.215.14")),
            patch.object(
                httpcore.SyncBackend,
                "connect_tcp",
                side_effect=httpcore.ConnectError("x"),
            ) as connect,
            self.assertRaises(httpx.ConnectError),
        ):
            # Act
            self.client.get("http://example.org/")

        # Assert
        self.assertEqual(connect.call_args.args[:2], ("93.184.215.14", 80))

    def test_tries_the_next_address_after_a_failed_connect(self):
        # Arrange
        with (
            patch(
                "socket.getaddrinfo",
                return_value=_resolves_to("93.184.215.14", "93.184.215.15"),
            ),
            patch.object(
                httpcore.SyncBackend,
                "connect_tcp",
                side_effect=[httpcore.ConnectTimeout("x"), httpcore.ConnectError("y")],
            ) as connect,
            self.assertRaises(httpx.ConnectError),
        ):
            # Act
            self.client.get("http://example.org/")

        # Assert
        self.assertEqual(
            [c.args[0] for c in connect.call_args_list],
            ["93.184.215.14", "93.184.215.15"],
        )

    def test_tries_at_most_three_addresses(self):
        # Arrange
        addresses = [f"93.184.215.{n}" for n in range(10, 20)]
        with (
            patch("socket.getaddrinfo", return_value=_resolves_to(*addresses)),
            patch.object(
                httpcore.SyncBackend,
                "connect_tcp",
                side_effect=httpcore.ConnectTimeout("x"),
            ) as connect,
            self.assertRaises(httpx.ConnectTimeout),
        ):
            # Act
            self.client.get("http://example.org/")

        # Assert
        self.assertEqual(connect.call_count, 3)

    def test_ignores_proxy_settings(self):
        # Arrange
        with patch.dict("os.environ", {"HTTP_PROXY": "http://10.0.0.1:3128"}):
            client = public_http_client(timeout=httpx.Timeout(1), headers={})

        # Assert
        self.assertFalse(client.trust_env)

    def test_public_unicast_addresses_are_public(self):
        # Act / Assert
        self.assertTrue(is_public_address("93.184.215.14"))
        self.assertTrue(is_public_address("2606:2800:21f:cb07:6820:80da:af6b:8b2c"))
        self.assertFalse(is_public_address("224.0.0.1"))
