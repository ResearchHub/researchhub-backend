import logging
import time
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db import transaction
from web3 import Web3

from ethereum.lib import (
    RSC_CONTRACT_ADDRESS,
    execute_erc20_transfer,
    get_gas_estimate,
    get_private_key,
)
from reputation.distributions import Distribution
from reputation.distributor import Distributor
from reputation.lib import contract_abi, get_gas_price_wei
from user.models import User
from utils.sentry import log_error
from utils.web3_utils import web3_provider

logger = logging.getLogger(__name__)
DEAD_ADDRESS = "0x000000000000000000000000000000000000dEaD"


class WalletService:
    """Service for managing wallet operations including RSC burning."""

    @staticmethod
    def burn_revenue_rsc(network: str = "BASE") -> Optional[str]:
        """
        Burn RSC from the revenue account.

        Args:
            network: "ETHEREUM" or "BASE" - which network to burn on

        Returns:
            Transaction hash if successful, None if no balance to burn
        """
        logger.info(f"Starting RSC burning on {network}")

        try:
            # Get the revenue account and check balance
            revenue_account = User.objects.get_community_revenue_account()
            current_balance = revenue_account.get_balance()

            if current_balance <= 0:
                logger.info(
                    f"Revenue account has no balance to burn: {current_balance}"
                )
                return None

            logger.info(f"Revenue account balance to burn: {current_balance}")

            # Phase 1: Try blockchain transaction FIRST
            tx_hash = WalletService._burn_tokens_from_hot_wallet(
                current_balance, network
            )

            # Phase 2: Only update database AFTER successful blockchain transaction
            with transaction.atomic():
                WalletService._zero_out_revenue_account(
                    revenue_account, current_balance
                )

            logger.info(
                f"Successfully burned {current_balance} RSC from revenue account on {network}"
            )
            return tx_hash

        except Exception as e:
            log_error(e, f"Failed to burn revenue RSC on {network}")
            raise

    @staticmethod
    def _zero_out_revenue_account(revenue_account: User, amount: Decimal) -> None:
        """Creates negative balance records to zero out the revenue account."""
        distribution = Distribution("RSC_BURN", -amount, give_rep=False)

        distributor = Distributor(
            distribution, revenue_account, revenue_account, time.time(), revenue_account
        )

        distributor.distribute()

    @staticmethod
    def _burn_tokens_from_hot_wallet(amount: Decimal, network: str = "BASE") -> str:
        """Transfers tokens from hot wallet to dead address (burning them)."""
        try:
            # Get the appropriate web3 provider and contract address
            if network == "BASE":
                w3 = web3_provider.base
                contract_address = settings.WEB3_BASE_RSC_ADDRESS
            else:
                w3 = web3_provider.ethereum
                contract_address = RSC_CONTRACT_ADDRESS

            contract = w3.eth.contract(
                abi=contract_abi, address=Web3.to_checksum_address(contract_address)
            )

            # Estimate gas cost before proceeding
            gas_estimate = get_gas_estimate(
                contract.functions.transfer(DEAD_ADDRESS, int(amount * 10**18))
            )

            # Use shared gas price calculation
            gas_price_wei = get_gas_price_wei(network)
            estimated_cost_wei = gas_estimate * gas_price_wei
            estimated_cost_eth = estimated_cost_wei / 10**18

            logger.info(
                f"Estimated gas cost for burning {amount} RSC: {estimated_cost_eth} ETH"
            )

            # Check hot wallet ETH balance
            eth_balance = w3.eth.get_balance(settings.WEB3_WALLET_ADDRESS)
            eth_balance_eth = eth_balance / 10**18

            if eth_balance < estimated_cost_wei * 1.2:  # 20% buffer
                error_msg = (
                    f"Insufficient ETH in hot wallet. Need ~{estimated_cost_eth} ETH, "
                    f"have {eth_balance_eth} ETH"
                )
                log_error(Exception(error_msg), error_msg)
                raise Exception(error_msg)

            # Execute the transfer to dead address
            tx_hash = execute_erc20_transfer(
                w3=w3,
                sender=settings.WEB3_WALLET_ADDRESS,
                sender_signing_key=get_private_key(),
                contract=contract,
                to=DEAD_ADDRESS,
                amount=amount,
                network=network,
            )

            logger.info(f"Burning transaction submitted: {tx_hash}")
            return tx_hash

        except Exception as e:
            log_error(e, f"Failed to burn {amount} RSC from hot wallet")
            raise
