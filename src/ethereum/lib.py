TOKENS = {
    'rhc': {
        'name': 'Research Coin',
        'contract_address': '0x7D50101BbFa12f4A1B4e6de0Dd58Ad36dE150D55',
        'ticker': 'rhc'
    }
}


def get_token_address_choices():
    return [
        (
            token['contract_address'],
            f'{token["name"]} address'
        ) for token in TOKENS.values()
    ]


TOKEN_ADDRESS_CHOICES = get_token_address_choices()


TOKEN_REPUTATION_EXCHANGE_RATES = {
    f'{TOKENS["rhc"]}': 0.1
}


def convert_reputation_amount_to_token_amount(token, reputation_amount):
    return TOKEN_REPUTATION_EXCHANGE_RATES[token] * reputation_amount
