import json
import logging

import ethereum.utils
import ethereum.lib
from researchhub.settings import ASYNC_SERVICE_HOST, WEB3_SHARED_SECRET
from utils.http import http_request, RequestMethods

WITHDRAWAL_MINIMUM = 75


class PendingWithdrawal:
    def __init__(self, withdrawal, starting_balance, balance_record_id):
        self.withdrawal = withdrawal
        self.balance_payout = starting_balance
        self.balance_record_id = balance_record_id

    def complete_token_transfer(self):
        self.withdrawal.set_paid_pending()
        self.token_payout = self._calculate_tokens_and_update_withdrawal_amount()  # noqa
        self._request_transfer('RSC')

    def _calculate_tokens_and_update_withdrawal_amount(self):
        token_payout, withdrawal_amount = ethereum.lib.convert_reputation_amount_to_token_amount(  # noqa: E501
            'RSC',
            self.balance_payout
        )
        self.withdrawal.amount = withdrawal_amount
        self.withdrawal.save()
        return token_payout

    def _request_transfer(self, token):
        url = ASYNC_SERVICE_HOST + '/ethereum/erc20transfer'
        message_raw = {
            "balance_record": self.balance_record_id,
            "withdrawal": self.withdrawal.id,
            "token": token,
            "to": self.withdrawal.to_address,
            "amount": self.token_payout
        }
        signature, message, public_key = ethereum.utils.sign_message(
            message_raw,
            WEB3_SHARED_SECRET
        )
        data = {
            "signature": signature,
            "message": message.hex(),
            "public_key": public_key
        }
        response = http_request(
            RequestMethods.POST,
            url,
            data=json.dumps(data),
            timeout=3
        )
        response.raise_for_status()
        logging.info(response.content)
        return response
