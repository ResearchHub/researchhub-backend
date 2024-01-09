import time


from reputation.distributions import (
    create_bounty_dao_fee_distribution,
    create_bounty_rh_fee_distribution,
    create_support_dao_fee_distribution,
    create_support_rh_fee_distribution,
)
from reputation.distributor import Distributor
from reputation.models import BountyFee, SupportFee
from user.models import User

def calculate_bounty_fees(gross_amount):
    return _calculate_fees(gross_amount, fee_model=BountyFee)

def calculate_support_fees(gross_amount,):
    return _calculate_fees(gross_amount, fee_model=SupportFee)

def _calculate_fees(
    gross_amount,
    fee_model = BountyFee,
):
    """
    Calculate fees using the current fee
    
    Args:
        gross_amount: The gross amount of the purchase
        fee_model: The fee model to use (i.e. type of fee)
        
    Returns:
        fee: The total fee
        rh_fee: The RH fee
        dao_fee: The DAO fee
        current_fee_obj: The current fee object
    """
    current_fee_obj = fee_model.objects.last()
    rh_pct = current_fee_obj.rh_pct
    dao_pct = current_fee_obj.dao_pct
    rh_fee = gross_amount * rh_pct
    dao_fee = gross_amount * dao_pct
    fee = rh_fee + dao_fee

    return fee, rh_fee, dao_fee, current_fee_obj


def deduct_bounty_fees(user, fee, rh_fee, dao_fee, current_fee_obj):
    return _deduct_fees(
        user, fee, rh_fee, dao_fee, current_fee_obj, fee_type="bounty"
    )


def deduct_support_fees(user, fee, rh_fee, dao_fee, current_fee_obj):
    return _deduct_fees(
        user, fee, rh_fee, dao_fee, current_fee_obj, fee_type="support"
    )


def _deduct_fees(
    user, fee, rh_fee, dao_fee, current_fee_obj,
    fee_type="bounty",
):
    """
    Deduct fees from the gross amount of the purchase.
    Creates a Distributor object for each fee and calls the distribute method.
    
    Args:
        user: The user making the purchase
        fee: BountyFee object
        rh_fee: The RH fee
        dao_fee: The DAO fee
        current_fee_obj: The current fee object
        fee_type: The type of fee (i.e. bounty or support)
    
    Returns:
        True if successful, else raises exception
    """
    rh_recipient = User.objects.get_revenue_account()
    dao_recipient = User.objects.get_community_account()
    if fee_type == "bounty":
        rh_fee_distribution = create_bounty_rh_fee_distribution(rh_fee)
        dao_fee_distribution = create_bounty_dao_fee_distribution(dao_fee)
    elif fee_type == "support":
        rh_fee_distribution = create_support_rh_fee_distribution(rh_fee)
        dao_fee_distribution = create_support_dao_fee_distribution(dao_fee)
    else:
        raise ValueError("Invalid fee type")
    rh_inc_distributor = Distributor(
        rh_fee_distribution,
        rh_recipient,
        current_fee_obj,
        time.time(),
        giver=user,
    )
    rh_inc_record = rh_inc_distributor.distribute()
    rh_dao_distributor = Distributor(
        dao_fee_distribution,
        dao_recipient,
        current_fee_obj,
        time.time(),
        giver=user,
    )
    rh_dao_record = rh_dao_distributor.distribute()

    if not (rh_inc_record and rh_dao_record):
        raise Exception("Failed to deduct fee")
    return True