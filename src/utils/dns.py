import socket
from typing import List


def resolve_dns(hosts: List[str]) -> List[str]:
    ip_addresses = set()
    for host in hosts:
        try:
            ips = list({result[4][0] for result in socket.getaddrinfo(host, None)})
            ip_addresses.update(ips)
        except Exception:
            ip_addresses.update([host])
    return list(ip_addresses)
