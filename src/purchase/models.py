from .related_models.aggregate_purchase_model import AggregatePurchase
from .related_models.balance_entry_date_model import BalanceEntryDate
from .related_models.balance_model import Balance
from .related_models.fundraise_model import Fundraise
from .related_models.funding_credit_model import FundingCredit
from .related_models.grant_application_model import GrantApplication
from .related_models.grant_model import Grant
from .related_models.payment_model import Payment
from .related_models.purchase_model import Purchase
from .related_models.rsc_exchange_rate_model import RscExchangeRate
from .related_models.staking_distribution_record_model import StakingDistributionRecord
from .related_models.staking_snapshot_model import StakingSnapshot
from .related_models.support_model import Support
from .related_models.usd_balance_model import UsdBalance
from .related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from .related_models.wallet_model import Wallet

migratables = (
    AggregatePurchase,
    Balance,
    BalanceEntryDate,
    Fundraise,
    FundingCredit,
    Grant,
    GrantApplication,
    Payment,
    Purchase,
    RscExchangeRate,
    StakingDistributionRecord,
    StakingSnapshot,
    Support,
    UsdBalance,
    UsdFundraiseContribution,
    Wallet,
)
