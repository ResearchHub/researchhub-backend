import requests
import os

BASE_URL = "https://api.originality.ai/api"
ENDPOINT_SCAN = "/v1/scan/ai"


def calculate_ai_score(text):
    """
    Send text to Originality.ai and return the probability (0.0–1.0) that the text is 
    AI-generated. Return score = -1 if response status is >= 400.

    return: A float between 0 and 1 if scoring succeeded. -1 if failed.
    """
    # FIXME: key should probably come from a secrets manager
    API_KEY = os.environ.get("ORIGINALITY_KEY")
    if not API_KEY:
        # TODO: Log error here.
        return -1

    url = f"{BASE_URL}{ENDPOINT_SCAN}"
    headers = {
        "Content-Type": "application/json",
        "X-OAI-API-KEY": API_KEY
    }
    data = {
        "title": "Scan",
        "content": text
    }

    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        result = resp.json()
    except Exception:
        return -1

    return result.get("score", {}).get("ai", -1)
