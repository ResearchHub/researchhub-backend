from .related_models.aggregate_purchase_model import AggregatePurchase
from .related_models.balance_model import Balance
from .related_models.fundraise_model import Fundraise
from .related_models.purchase_model import Purchase
from .related_models.rsc_exchange_rate_model import RscExchangeRate
from .related_models.support_model import Support
from .related_models.wallet_model import Wallet

migratables = (
    AggregatePurchase,
    Balance,
    Purchase,
    RscExchangeRate,
    Support,
    Wallet,
)
