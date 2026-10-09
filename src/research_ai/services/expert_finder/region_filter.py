"""Map expert-finder ``Region`` choices to ISO country codes for hard filtering.

OpenAlex exposes ``last_known_institutions.country_code`` (ISO 3166-1 alpha-2).
Server-side gates use these sets so the agent cannot submit out-of-region
authors. US state remains a soft preference (prompt / affiliation string), not
a hard country-code filter.
"""

from __future__ import annotations

from research_ai.constants import EXPERT_FINDER_DEFAULT_STATE, Region

# ISO 3166-1 alpha-2 codes aligned with Region descriptions in prompts.
_US_CODES: frozenset[str] = frozenset({"US"})

_EUROPE_CODES: frozenset[str] = frozenset(
    {
        "AD",
        "AL",
        "AT",
        "BA",
        "BE",
        "BG",
        "BY",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FO",
        "FR",
        "GB",
        "GG",
        "GI",
        "GR",
        "HR",
        "HU",
        "IE",
        "IM",
        "IS",
        "IT",
        "JE",
        "LI",
        "LT",
        "LU",
        "LV",
        "MC",
        "MD",
        "ME",
        "MK",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "RS",
        "RU",
        "SE",
        "SI",
        "SJ",
        "SK",
        "SM",
        "UA",
        "VA",
        "XK",
    }
)

_ASIA_PACIFIC_CODES: frozenset[str] = frozenset(
    {
        "AF",
        "AM",
        "AU",
        "AZ",
        "BD",
        "BN",
        "BT",
        "CC",
        "CN",
        "CK",
        "CX",
        "FJ",
        "FM",
        "GE",
        "GU",
        "HK",
        "ID",
        "IN",
        "JP",
        "KG",
        "KH",
        "KI",
        "KP",
        "KR",
        "KZ",
        "LA",
        "LK",
        "MH",
        "MM",
        "MN",
        "MO",
        "MP",
        "MV",
        "MY",
        "NC",
        "NF",
        "NP",
        "NR",
        "NU",
        "NZ",
        "PG",
        "PH",
        "PK",
        "PW",
        "SB",
        "SG",
        "TH",
        "TJ",
        "TL",
        "TM",
        "TO",
        "TV",
        "TW",
        "UZ",
        "VN",
        "VU",
        "WF",
        "WS",
    }
)

_AFRICA_MENA_CODES: frozenset[str] = frozenset(
    {
        "AE",
        "AO",
        "BF",
        "BH",
        "BI",
        "BJ",
        "BW",
        "CD",
        "CF",
        "CG",
        "CI",
        "CM",
        "CV",
        "DJ",
        "DZ",
        "EG",
        "EH",
        "ER",
        "ET",
        "GA",
        "GH",
        "GM",
        "GN",
        "GQ",
        "GW",
        "IL",
        "IQ",
        "IR",
        "JO",
        "KE",
        "KM",
        "KW",
        "LB",
        "LR",
        "LS",
        "LY",
        "MA",
        "MG",
        "ML",
        "MR",
        "MU",
        "MW",
        "MZ",
        "NA",
        "NE",
        "NG",
        "OM",
        "PS",
        "QA",
        "RW",
        "SA",
        "SC",
        "SD",
        "SL",
        "SN",
        "SO",
        "SS",
        "ST",
        "SY",
        "SZ",
        "TD",
        "TG",
        "TN",
        "TR",
        "TZ",
        "UG",
        "YE",
        "ZA",
        "ZM",
        "ZW",
    }
)

# Positive allow-lists (NON_US / ALL_REGIONS handled specially).
_REGION_ALLOW_CODES: dict[str, frozenset[str]] = {
    Region.US: _US_CODES,
    Region.EUROPE: _EUROPE_CODES,
    Region.ASIA_PACIFIC: _ASIA_PACIFIC_CODES,
    Region.AFRICA_MENA: _AFRICA_MENA_CODES,
}


def country_codes_for_region(region: str) -> frozenset[str] | None:
    """Return allowed ISO country codes for ``region``, or ``None`` if unrestricted.

    ``ALL_REGIONS`` and ``NON_US`` return ``None`` (no positive allow-list);
    callers must use :func:`author_matches_region` for ``NON_US``.
    """
    if region in (Region.ALL_REGIONS, Region.NON_US):
        return None
    return _REGION_ALLOW_CODES.get(region)


def institution_country_codes(author_record: dict | None) -> set[str]:
    """Collect ISO country codes from an OpenAlex author entity.

    Prefers ``last_known_institutions``; falls back to ``affiliations`` when
    last-known is empty or lacks codes.
    """
    record = author_record or {}
    codes: set[str] = set()
    for inst in record.get("last_known_institutions") or []:
        code = str((inst or {}).get("country_code") or "").strip().upper()
        if code:
            codes.add(code)
    if codes:
        return codes
    for aff in record.get("affiliations") or []:
        inst = (aff or {}).get("institution") or {}
        code = str(inst.get("country_code") or "").strip().upper()
        if code:
            codes.add(code)
    return codes


def author_matches_region(author_record: dict | None, region: str) -> bool:
    """True when the author's institutions satisfy the hard region filter."""
    if not region or region == Region.ALL_REGIONS:
        return True
    codes = institution_country_codes(author_record)
    if not codes:
        # Cannot verify geography — fail closed when a region is required.
        return False
    if region == Region.US:
        return "US" in codes
    if region == Region.NON_US:
        return any(code != "US" for code in codes)
    allowed = _REGION_ALLOW_CODES.get(region)
    if allowed is None:
        return True
    return bool(codes & allowed)


def affiliation_mentions_state(
    text: str | None,
    state: str | None,
    *,
    default_state: str = EXPERT_FINDER_DEFAULT_STATE,
) -> bool:
    """Soft US-state signal: case-insensitive substring match on affiliation text.

    Not a hard gate — OpenAlex has limited state granularity. Empty / default
    state returns False (no preference signal).
    """
    state_value = str(state or "").strip()
    if not state_value or state_value == default_state:
        return False
    haystack = str(text or "").casefold()
    return bool(haystack) and state_value.casefold() in haystack
