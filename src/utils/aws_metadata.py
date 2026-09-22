import requests

EC2_METADATA_URL = "http://169.254.169.254/latest"
TIMEOUT = 1


def ec2_private_ip() -> str:
    """
    Read the instance's private IP from the metadata service (IMDSv2).
    """
    token = requests.put(
        f"{EC2_METADATA_URL}/api/token",
        timeout=TIMEOUT,
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
    )
    token.raise_for_status()

    ip = requests.get(
        f"{EC2_METADATA_URL}/meta-data/local-ipv4",
        timeout=TIMEOUT,
        headers={"X-aws-ec2-metadata-token": token.text},
    )
    ip.raise_for_status()
    return ip.text
