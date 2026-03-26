import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/researchcoin"
REQUEST_TIMEOUT = 15  # seconds


class RscSupplyService:
    @staticmethod
    def fetch_circulating_supply():
        """Fetch circulating supply from CoinGecko.

        Returns the circulating supply as a Decimal.
        Raises on failure so callers can handle retries.
        """
        headers = requests.utils.default_headers()
        api_key = getattr(settings, "COIN_GECKO_API_KEY", "")
        if api_key:
            headers["x-cg-demo-api-key"] = api_key

        response = requests.get(
            COINGECKO_COIN_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            },
        )
        response.raise_for_status()

        data = response.json()
        supply = data["market_data"]["circulating_supply"]

        if supply is None or supply <= 0:
            raise ValueError(f"CoinGecko returned invalid circulating supply: {supply}")

        return Decimal(str(supply))
