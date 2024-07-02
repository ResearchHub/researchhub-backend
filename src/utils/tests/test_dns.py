import socket
import unittest
from unittest.mock import patch
from utils.dns import resolve_dns


def mock_getaddrinfo_side_effect(dns_name: str, *args, **kwargs):
    mock_responses = {
        "researchhub.com": [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.168.1.1", 0),
            )
        ],
        "researchhub.org": [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.168.2.2", 0),
            )
        ],
    }
    if dns_name in mock_responses:
        return mock_responses[dns_name]
    raise socket.gaierror


class TestResolveDNS(unittest.TestCase):

    @patch("socket.getaddrinfo")
    def test_resolve_dns(self, mock_getaddrinfo):
        # arrange
        mock_getaddrinfo.side_effect = mock_getaddrinfo_side_effect
        dns_names = ["researchhub.com", "researchhub.org"]
        expected_ips = ["192.168.1.1", "192.168.2.2"]

        # act
        resolved_ips = resolve_dns(dns_names)

        # asset
        self.assertCountEqual(resolved_ips, expected_ips)

    @patch("socket.getaddrinfo")
    def test_resolve_dns_with_error(self, mock_getaddrinfo):
        # arrange
        mock_getaddrinfo.side_effect = mock_getaddrinfo_side_effect
        dns_names = ["researchhub.com", "invalid.org"]
        expected_ips = ["192.168.1.1", "invalid.org"]

        # act
        resolved_ips = resolve_dns(dns_names)

        # assert
        self.assertCountEqual(resolved_ips, expected_ips)
