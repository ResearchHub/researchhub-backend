from .related_models.aggregate_purchase_model import AggregatePurchase
from .related_models.balance_model import Balance
from .related_models.purchase_model import Purchase
from .related_models.support_model import Support
from .related_models.wallet_model import Wallet

migratables = (
    AggregatePurchase,
    Balance,
    Purchase,
    Support,
    Wallet,
)
