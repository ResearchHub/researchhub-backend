import os

import requests

EC2_METADATA_URL = "http://169.254.169.254/latest"
ECS_METADATA_URI_VARIABLE = "ECS_CONTAINER_METADATA_URI_V4"
TIMEOUT = 1


def private_ip() -> str:
    """
    Returns the private IP of the current instance or ECS task.
    """
    if ECS_METADATA_URI_VARIABLE in os.environ:
        return ecs_task_private_ip()
    return ec2_private_ip()


def ecs_task_private_ip() -> str:
    """
    Reads the private IP of the ECS task from the ECS container metadata endpoint.
    """
    response = requests.get(os.environ[ECS_METADATA_URI_VARIABLE], timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()["Networks"][0]["IPv4Addresses"][0]


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
