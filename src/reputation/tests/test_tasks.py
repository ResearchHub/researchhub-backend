import time
from datetime import timedelta
from unittest.mock import Mock, patch

from django.conf import settings
from rest_framework.test import APITestCase
from web3.types import BlockData, TxData

from reputation.tasks import PENDING_TRANSACTION_TTL, check_deposits
from reputation.tests.helpers import create_deposit
from user.tests.helpers import create_random_authenticated_user

# Test addresses for mocking
TEST_WEB3_RSC_ADDRESS = "0x1234567890123456789012345678901234567890"
TEST_WEB3_WALLET_ADDRESS = "0x9876543210987654321098765432109876543210"


class TaskTests(APITestCase):
    def mock_get_transaction_receipt_data(self, transaction_hash, w3):
        # Create mock log entry for Transfer event
        mock_log = Mock()
        mock_log.address = TEST_WEB3_RSC_ADDRESS

        tx_receipt = {"status": 1, "logs": [mock_log]}
        return tx_receipt

    def mock_get_transaction_data(self, transaction_hash, w3):
        tx = TxData()
        tx["blockNumber"] = 0
        tx["input"] = "0x"
        return tx

    def mock_get_block_data(self, timestamp=time.time()):
        def _mock_get_block_data(block_number, w3):
            block = BlockData()
            block["timestamp"] = timestamp
            return block

        return _mock_get_block_data

    def mock_transfer_event(self):
        """Mock Transfer event with proper structure"""
        mock_event = Mock()
        mock_event.args = {
            "_from": "0x0000000000000000000000000000000000000000",
            "_to": TEST_WEB3_WALLET_ADDRESS,
            "_amount": 2000 * 10**18,
        }
        return mock_event

    def setUp(self):
        # Create a patcher for each function to be mocked
        self.get_transaction_receipt_patcher = patch(
            "reputation.tasks.get_transaction_receipt"
        )
        self.get_transaction_patcher = patch("reputation.tasks.get_transaction")
        self.get_block_patcher = patch("reputation.tasks.get_block")
        self.get_contract_patcher = patch("reputation.tasks.get_contract")

        # Add patches for the Web3 settings to ensure they have proper test values
        self.web3_rsc_address_patcher = patch.object(
            settings, "WEB3_RSC_ADDRESS", TEST_WEB3_RSC_ADDRESS
        )
        self.web3_wallet_address_patcher = patch.object(
            settings, "WEB3_WALLET_ADDRESS", TEST_WEB3_WALLET_ADDRESS
        )

        # Also patch the RSC_CONTRACT_ADDRESS constant that's imported from ethereum.lib
        self.rsc_contract_address_patcher = patch(
            "reputation.tasks.RSC_CONTRACT_ADDRESS", TEST_WEB3_RSC_ADDRESS
        )

        # Start the patchers and get the mock objects
        self.mock_get_transaction_receipt = self.get_transaction_receipt_patcher.start()
        self.mock_get_transaction = self.get_transaction_patcher.start()
        self.mock_get_block = self.get_block_patcher.start()
        self.mock_get_contract = self.get_contract_patcher.start()
        self.web3_rsc_address_patcher.start()
        self.web3_wallet_address_patcher.start()
        self.rsc_contract_address_patcher.start()

        # Set the return values for the mock objects
        self.mock_get_transaction_receipt.side_effect = (
            self.mock_get_transaction_receipt_data
        )
        self.mock_get_transaction.side_effect = self.mock_get_transaction_data
        self.mock_get_block.side_effect = self.mock_get_block_data(time.time())

        # Mock contract with Transfer event processing
        mock_contract = Mock()
        mock_transfer_event_handler = Mock()
        mock_transfer_event_handler.process_log.return_value = (
            self.mock_transfer_event()
        )
        mock_contract.events.Transfer.return_value = mock_transfer_event_handler
        self.mock_get_contract.return_value = mock_contract

    def tearDown(self):
        # Stop the patchers
        self.get_transaction_receipt_patcher.stop()
        self.get_transaction_patcher.stop()
        self.get_block_patcher.stop()
        self.get_contract_patcher.stop()
        self.web3_rsc_address_patcher.stop()
        self.web3_wallet_address_patcher.stop()
        self.rsc_contract_address_patcher.stop()

    def test_check_deposits(self):
        user = create_random_authenticated_user("deposit_user")

        deposit1 = create_deposit(
            user, "2000.5", "from_address_1", "transaction_hash_1"
        )

        deposit2 = create_deposit(
            user, "2000.0", "from_address_2", "transaction_hash_2"
        )

        check_deposits()

        deposit1.refresh_from_db()
        deposit2.refresh_from_db()

        self.assertEqual(deposit1.paid_status, "PAID")
        self.assertEqual(deposit2.paid_status, "PAID")

    def test_check_repeat_deposit_fails(self):
        user = create_random_authenticated_user("deposit_user")
        transaction_hash = "transaction_hash_3"

        deposit = create_deposit(user, "2000.0", "from_address_3", transaction_hash)
        repeat_deposit = create_deposit(
            user, "2000.0", "from_address_3", transaction_hash
        )

        check_deposits()

        deposit.refresh_from_db()
        repeat_deposit.refresh_from_db()

        self.assertEqual(deposit.paid_status, "PAID")
        self.assertEqual(repeat_deposit.paid_status, "FAILED")

    def test_old_pending_deposit(self):
        user = create_random_authenticated_user("deposit_user")

        deposit = create_deposit(user, "2000.0", "from_address_4", "transaction_hash_4")
        deposit.created_date = deposit.created_date - timedelta(
            seconds=PENDING_TRANSACTION_TTL + 1
        )
        deposit.save()

        check_deposits()

        deposit.refresh_from_db()

        self.assertEqual(deposit.paid_status, "FAILED")

    def test_old_transaction_hash(self):
        # Reset the mock for get_block_data to return a block with an old timestamp.
        self.mock_get_block.side_effect = self.mock_get_block_data(
            time.time() - PENDING_TRANSACTION_TTL - 1
        )

        user = create_random_authenticated_user("deposit_user")

        deposit = create_deposit(user, "2000.0", "from_address_5", "transaction_hash_5")
        deposit.transaction_hash = "old_transaction_hash"
        deposit.save()

        check_deposits()

        deposit.refresh_from_db()

        self.assertEqual(deposit.paid_status, "FAILED")

    def test_transaction_exception(self):
        user = create_random_authenticated_user("deposit_user")

        deposit = create_deposit(user, "2000.0", "from_address_6", "transaction_hash_6")
        self.mock_get_transaction.side_effect = ValueError

        check_deposits()

        deposit.refresh_from_db()

        self.assertEqual(deposit.paid_status, "PENDING")

    def test_no_transfer_events_fails(self):
        """Test that deposits fail when no Transfer events are found"""
        user = create_random_authenticated_user("deposit_user")

        # Override the mock to return empty logs
        def mock_empty_receipt(transaction_hash, w3):
            tx_receipt = {"status": 1, "logs": []}  # No logs
            return tx_receipt

        self.mock_get_transaction_receipt.side_effect = mock_empty_receipt

        deposit = create_deposit(user, "2000.0", "from_address_7", "transaction_hash_7")

        check_deposits()

        deposit.refresh_from_db()
        self.assertEqual(deposit.paid_status, "FAILED")

    def test_wrong_recipient_address_fails(self):
        """Test that deposits fail when Transfer event has wrong recipient"""
        user = create_random_authenticated_user("deposit_user")

        # Create mock Transfer event with wrong recipient
        def mock_wrong_recipient_event():
            mock_event = Mock()
            mock_event.args = {
                "_from": "0x0000000000000000000000000000000000000000",
                "_to": "0x1111111111111111111111111111111111111111",  # Wrong address
                "_amount": 2000 * 10**18,
            }
            return mock_event

        # Override the contract mock
        mock_contract = Mock()
        mock_transfer_event_handler = Mock()
        mock_transfer_event_handler.process_log.return_value = (
            mock_wrong_recipient_event()
        )
        mock_contract.events.Transfer.return_value = mock_transfer_event_handler
        self.mock_get_contract.return_value = mock_contract

        deposit = create_deposit(user, "2000.0", "from_address_8", "transaction_hash_8")

        check_deposits()

        deposit.refresh_from_db()
        self.assertEqual(deposit.paid_status, "FAILED")
