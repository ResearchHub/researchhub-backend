import json
import logging

import ethereum.utils
import ethereum.lib
from reputation.exceptions import ReputationSignalError
from researchhub.settings import ASYNC_SERVICE_HOST, WEB3_SHARED_SECRET
from utils.http import http_request, RequestMethods

FIRST_WITHDRAWAL_MINIMUM = 75


class PendingWithdrawal:
    def __init__(self, withdrawal):
        self.withdrawal = withdrawal

    def complete_token_transfer(self):
        self.balance_payout = self.withdrawal.user.get_balance()
        if self.balance_payout <= 0:
            # TODO: Change this to PendingWithdrawalError
            raise ReputationSignalError(
                None,
                'Insufficient balance to pay out'
            )
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
