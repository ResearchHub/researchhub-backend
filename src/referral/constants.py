"""
Constants for the referral system.

These constants are shared across all referral-related services and models.
"""

from decimal import Decimal

# Referral bonus percentage (as a percentage, e.g., 10.00 = 10%)
REFERRAL_BONUS_PERCENTAGE = Decimal("10.00")

# Number of months a referral is eligible for bonuses after signup
REFERRAL_ELIGIBILITY_MONTHS = 6
