"""An httpx client for URLs the server did not choose, which reaches public hosts only.

Addresses are checked when each connection opens, after DNS and on every
redirect hop, and the connection goes to the address that was checked, so a
rebinding DNS answer cannot slip a private address in between.
"""

import ipaddress
import socket

import httpcore
import httpx

_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class UnsafeAddressError(Exception):
    """The host resolves to an address that is not on the public internet."""


def is_public_address(address: str) -> bool:
    """Whether ``address`` is a global unicast address, embedded IPv4 included."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


class _PublicOnlyBackend(httpcore.SyncBackend):
    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError) as exc:
            raise httpcore.ConnectError(f"cannot resolve {host}") from exc
        addresses = list(dict.fromkeys(info[4][0] for info in infos))
        if not addresses or not all(map(is_public_address, addresses)):
            raise UnsafeAddressError(f"{host} is not a public internet address")
        error = None
        for address in addresses:
            try:
                return super().connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except httpcore.ConnectError as exc:
                error = exc
        raise error


class PublicOnlyTransport(httpx.HTTPTransport):
    """An HTTP/1.1 transport whose connections only reach public addresses."""

    def __init__(self):
        super().__init__()
        # httpx takes no network backend, so its pool is rebuilt with one.
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            # Fetches are one-offs; no idle connection is left open.
            max_keepalive_connections=0,
            network_backend=_PublicOnlyBackend(),
        )


def public_http_client(*, timeout: httpx.Timeout, headers: dict) -> httpx.Client:
    """A client that follows no redirects and ignores proxy settings."""
    return httpx.Client(
        transport=PublicOnlyTransport(),
        timeout=timeout,
        headers=headers,
        follow_redirects=False,
        trust_env=False,
    )
