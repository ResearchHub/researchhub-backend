"""
Bot detection utilities for identifying automated requests.

Detects bots through:
- User agent filtering (obvious bots)
- Header fingerprinting (missing browser headers)
- Whitelist for legitimate search bots
"""

import logging
import re

from rest_framework.exceptions import PermissionDenied

from utils.http import get_client_ip

logger = logging.getLogger(__name__)

# Blocked user agents (obvious bots/scrapers)
BLOCKED_USER_AGENTS = [
    r"bot",
    r"crawler",
    r"spider",
    r"scraper",
    r"wget",
    r"curl",
    r"python-requests",
    r"scrapy",
    r"beautifulsoup",
    r"selenium",
    r"phantomjs",
    r"puppeteer",
    r"headless",
    r"axios",
    r"go-http-client",
    r"java/",
    r"httpclient",
    r"okhttp",
]

# Allowed bots (legitimate search engines)
ALLOWED_BOTS = [
    r"googlebot",
    r"bingbot",
    r"slackbot",
    r"twitterbot",
    r"facebookexternalhit",
    r"linkedinbot",
    r"applebot",
    r"baiduspider",
    r"yandexbot",
]


def is_allowed_bot(user_agent: str) -> bool:
    """
    Check if user agent is a whitelisted legitimate bot.
    """
    if not user_agent:
        return False

    user_agent_lower = user_agent.lower()
    for allowed_pattern in ALLOWED_BOTS:
        if re.search(allowed_pattern, user_agent_lower):
            return True
    return False


def is_blocked_user_agent(user_agent: str) -> bool:
    """
    Check if user agent matches blocked bot patterns.
    Returns True if user agent should be blocked.
    """
    if not user_agent:
        return True  # Missing user agent is suspicious

    user_agent_lower = user_agent.lower()

    # Check if it's an allowed bot first
    if is_allowed_bot(user_agent):
        return False

    # Check against blocked patterns
    for blocked_pattern in BLOCKED_USER_AGENTS:
        if re.search(blocked_pattern, user_agent_lower):
            return True

    return False


def _check_missing_headers(accept_language: str, accept_encoding: str) -> list:
    issues = []
    if not accept_language:
        issues.append("missing_accept_language")
    if not accept_encoding:
        issues.append("missing_accept_encoding")
    return issues


def _check_chrome_headers(request, user_agent: str) -> list:
    issues = []
    if "chrome" in user_agent.lower():
        sec_ch_ua = request.META.get("HTTP_SEC_CH_UA", "")
        if not sec_ch_ua and "mobile" not in user_agent.lower():
            if not is_allowed_bot(user_agent):
                issues.append("fake_chrome_ua")
    return issues


def _check_accept_header(user_agent: str, accept: str) -> list:
    issues = []
    if "mozilla" in user_agent.lower() and "text/html" not in accept.lower():
        if "application/json" not in accept.lower():
            if not is_allowed_bot(user_agent):
                issues.append("ua_accept_mismatch")
    return issues


def _check_js_headers(request, user_agent: str) -> list:
    issues = []
    sec_fetch_dest = request.META.get("HTTP_SEC_FETCH_DEST", "")
    if sec_fetch_dest and any(
        bot in user_agent.lower() for bot in ["bot", "crawler", "spider"]
    ):
        issues.append("bot_with_js_headers")
    return issues


def calculate_browser_fingerprint(request) -> dict:
    """
    Analyze request headers for bot-like patterns.
    Returns dict with 'suspicious', 'issues', and 'confidence' fields.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    accept = request.META.get("HTTP_ACCEPT", "")
    accept_language = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    accept_encoding = request.META.get("HTTP_ACCEPT_ENCODING", "")

    issues = []
    issues.extend(_check_missing_headers(accept_language, accept_encoding))
    issues.extend(_check_chrome_headers(request, user_agent))
    issues.extend(_check_accept_header(user_agent, accept))
    issues.extend(_check_js_headers(request, user_agent))

    return {
        "suspicious": len(issues) > 0,
        "issues": issues,
        "confidence": min(len(issues) * 0.25, 1.0),
    }


def validate_request_headers(request) -> None:
    """
    Validate request headers for bot detection.
    Raises PermissionDenied if bot detected.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    ip = get_client_ip(request)

    if is_blocked_user_agent(user_agent):
        logger.warning(f"Blocked request from blocked user agent from IP: {ip}")
        raise PermissionDenied("Automated requests are not allowed")

    fingerprint = calculate_browser_fingerprint(request)
    if fingerprint["suspicious"] and fingerprint["confidence"] > 0.5:
        issue_count = len(fingerprint["issues"])
        logger.warning(
            f"Suspicious headers detected: {issue_count} issue(s) from IP: {ip}"
        )
        if fingerprint["confidence"] > 0.7:
            raise PermissionDenied("Suspicious request patterns detected")
