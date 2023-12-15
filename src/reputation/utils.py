import time


from reputation.distributions import (
    create_bounty_dao_fee_distribution,
    create_bounty_rh_fee_distribution,
)
from reputation.distributor import Distributor
from reputation.models import BountyFee
from user.models import User

def calculate_fees(gross_amount):
    """
    Calculate fees using the current bounty fee
    
    Args:
        gross_amount: The gross amount of the purchase
        
    Returns:
        fee: The total fee
        rh_fee: The RH fee
        dao_fee: The DAO fee
        current_bounty_fee: The current bounty fee
    """
    current_bounty_fee = BountyFee.objects.last()
    rh_pct = current_bounty_fee.rh_pct
    dao_pct = current_bounty_fee.dao_pct
    rh_fee = gross_amount * rh_pct
    dao_fee = gross_amount * dao_pct
    fee = rh_fee + dao_fee

    return fee, rh_fee, dao_fee, current_bounty_fee


def deduct_fees(user, fee, rh_fee, dao_fee, current_bounty_fee):
    """
    Deduct fees from the gross amount of the purchase.
    Creates a Distributor object for each fee and calls the distribute method.
    
    Args:
        user: The user making the purchase
        fee: BountyFee object
        rh_fee: The RH fee
        dao_fee: The DAO fee
        current_bounty_fee: The current bounty fee
    
    Returns:
        True if successful, else raises exception
    """
    rh_recipient = User.objects.get_revenue_account()
    dao_recipient = User.objects.get_community_account()
    rh_fee_distribution = create_bounty_rh_fee_distribution(rh_fee)
    dao_fee_distribution = create_bounty_dao_fee_distribution(dao_fee)
    rh_inc_distributor = Distributor(
        rh_fee_distribution,
        rh_recipient,
        current_bounty_fee,
        time.time(),
        giver=user,
    )
    rh_inc_record = rh_inc_distributor.distribute()
    rh_dao_distributor = Distributor(
        dao_fee_distribution,
        dao_recipient,
        current_bounty_fee,
        time.time(),
        giver=user,
    )
    rh_dao_record = rh_dao_distributor.distribute()

    if not (rh_inc_record and rh_dao_record):
        raise Exception("Failed to deduct fee")
    return True