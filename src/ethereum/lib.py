from decimal import Decimal
from ethereum.utils import decimal_to_token_amount

TOKENS = {
    'rhc': {
        'name': 'Research Coin',
        'contract_address': '0x7D50101BbFa12f4A1B4e6de0Dd58Ad36dE150D55',
        'ticker': 'rhc',
        'denomination': 18,
        'reputation_exchange_rate': '0.1'
    }
}

RESEARCHCOIN_CONTRACT_ADDRESS = TOKENS['rhc']['contract_address']  # convenient


def get_token_address_choices():
    return [
        (
            token['contract_address'],
            f'{token["name"]} address'
        ) for token in TOKENS.values()
    ]


TOKEN_ADDRESS_CHOICES = get_token_address_choices()


def convert_reputation_amount_to_token_amount(token, reputation_amount):
    """Converts `reputation_amount` based on the `token` reputation exchange
    rate.

    Returns:
        (int, str) -- Amount of `token` in integer and decimal forms.
    """

    if reputation_amount < 0:
        raise ValueError('`reputation_amount` must be a positive number')

    token = TOKENS[token]
    rate = Decimal(str(token['reputation_exchange_rate']))
    reputation = Decimal(str(reputation_amount))
    total = rate * reputation
    denomination = token['denomination']
    return decimal_to_token_amount(total, denomination), str(total)
