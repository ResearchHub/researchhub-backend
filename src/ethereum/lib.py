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
