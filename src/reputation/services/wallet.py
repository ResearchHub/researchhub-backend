import logging
import time
from decimal import Decimal
from typing import Optional

from django.conf import settings
from web3 import Web3

from ethereum.lib import (
    RSC_CONTRACT_ADDRESS,
    execute_erc20_transfer,
    get_gas_estimate,
    get_private_key,
)
from reputation.distributions import Distribution
from reputation.distributor import Distributor
from reputation.lib import contract_abi
from user.models import User
from utils.sentry import log_error
from utils.web3_utils import web3_provider

logger = logging.getLogger(__name__)
NULL_ADDRESS = "0x0000000000000000000000000000000000000000"


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
            # Get the revenue account
            revenue_account = User.objects.get_community_revenue_account()

            # Get current balance (excluding locked funds)
            current_balance = revenue_account.get_balance()

            if current_balance <= 0:
                logger.info(
                    f"Revenue account has no balance to burn: {current_balance}"
                )
                return None

            logger.info(f"Revenue account balance to burn: {current_balance}")

            # Step 1: Create negative balance records to zero out the account
            WalletService._zero_out_revenue_account(revenue_account, current_balance)

            # Step 2: Burn tokens from hot wallet
            tx_hash = WalletService._burn_tokens_from_hot_wallet(
                current_balance, network
            )

            logger.info(
                f"Successfully burned {current_balance} RSC from revenue account "
                f"on {network}"
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
        """Transfers tokens from hot wallet to null address (burning them)."""
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
                contract.functions.transfer(NULL_ADDRESS, int(amount * 10**18))
            )
            gas_price = w3.eth.generate_gas_price()
            estimated_cost_wei = gas_estimate * gas_price
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

            # Execute the transfer to null address
            tx_hash = execute_erc20_transfer(
                w3=w3,
                sender=settings.WEB3_WALLET_ADDRESS,
                sender_signing_key=get_private_key(),
                contract=contract,
                to=NULL_ADDRESS,
                amount=amount,
                network=network,
            )

            logger.info(f"Burning transaction submitted: {tx_hash}")
            return tx_hash

        except Exception as e:
            log_error(e, f"Failed to burn {amount} RSC from hot wallet")
            raise

    @staticmethod
    def get_hot_wallet_balance(network: str = "BASE") -> dict:
        """Get hot wallet balances for a specific network."""
        try:
            if network == "BASE":
                w3 = web3_provider.base
                contract_address = settings.WEB3_BASE_RSC_ADDRESS
            else:
                w3 = web3_provider.ethereum
                contract_address = RSC_CONTRACT_ADDRESS

            eth_balance = w3.eth.get_balance(settings.WEB3_WALLET_ADDRESS)
            eth_balance_eth = eth_balance / 10**18

            contract = w3.eth.contract(
                abi=contract_abi, address=Web3.to_checksum_address(contract_address)
            )
            rsc_balance = contract.functions.balanceOf(
                settings.WEB3_WALLET_ADDRESS
            ).call()
            rsc_balance_human = rsc_balance / 10**18

            return {
                "network": network,
                "eth_balance": eth_balance_eth,
                "rsc_balance": rsc_balance_human,
            }

        except Exception as e:
            log_error(e, f"Failed to get hot wallet balance for {network}")
            raise
