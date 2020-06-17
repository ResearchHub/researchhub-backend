import json
import logging

from django.db import transaction

import ethereum.utils
import ethereum.lib
from reputation.exceptions import ReputationSignalError
from reputation.models import Distribution
from reputation.utils import get_total_reputation_from_distributions
from researchhub.settings import ASYNC_SERVICE_HOST, WEB3_SHARED_SECRET
from utils.http import http_request, RequestMethods

FIRST_WITHDRAWAL_MINIMUM = 75


class PendingWithdrawal:
    def __init__(self, withdrawal, distributions):
        self.withdrawal = withdrawal
        self.distributions = self.add_withdrawal_to_distributions(
            distributions
        )
        self.reputation_payout = self.calculate_reputation_payout()
        self.token_payout = self.calculate_tokens_and_withdrawal_amount()

    def add_withdrawal_to_distributions(self, distributions):
        pending_distributions = []
        for distribution in distributions:
            try:
                with transaction.atomic():
                    distribution.set_paid_pending()
                    distribution.set_withdrawal(self.withdrawal)
                    pending_distributions.append(distribution)
            except Exception as e:
                logging.error(e)
        return pending_distributions

    def calculate_reputation_payout(self):
        reputation_payout = get_total_reputation_from_distributions(
            self.distributions
        )
        if reputation_payout <= 0:
            raise ReputationSignalError(
                None,
                'Insufficient balance to pay out'
            )
        return reputation_payout

    def calculate_tokens_and_withdrawal_amount(self):
        token_payout, withdrawal_amount = ethereum.lib.convert_reputation_amount_to_token_amount(  # noqa: E501
            'rsc',
            self.reputation_payout
        )
        self.withdrawal.amount = withdrawal_amount
        self.withdrawal.save()
        return token_payout

    def complete_token_transfer(self):
        try:
            self.withdrawal.set_paid_pending()
            self.request_transfer('RSC')
        except Exception as e:
            self.fail_distributions()
            raise e

    def request_transfer(self, token):
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
        logging.error(response.content)
        return response

    def fail_distributions(self):
        for distribution in self.distributions:
            try:
                distribution.set_paid_failed()
            except Exception:
                pass


def get_unpaid_distributions(user):
    return user.reputation_records.filter(
        paid_status=None,
        distributed_status=Distribution.DISTRIBUTED
    )


def get_user_balance(user):
    unpaid_distributions = get_unpaid_distributions(user)
    return get_total_reputation_from_distributions(unpaid_distributions)
