from decimal import Decimal

# Multiplier tiers: (min_days, max_days, multiplier)
# Time-weighted multipliers reward longer holding periods
STAKING_MULTIPLIER_TIERS = [
    (0, 30, Decimal("1.0")),  # 0-30 days: 1.0x
    (30, 90, Decimal("2.5")),  # 30-90 days: 2.5x
    (90, 180, Decimal("4.0")),  # 90-180 days: 4.0x
    (180, 365, Decimal("6.0")),  # 180-365 days: 6.0x
    (365, None, Decimal("7.5")),  # 365+ days: 7.5x
]

# Weekly distribution pool (funding credits to distribute each week)
WEEKLY_STAKING_POOL = Decimal("10000")  # 10,000 credits/week

# Minimum RSC balance to receive staking rewards
MINIMUM_STAKING_BALANCE = Decimal("100")

# Tier names for display
STAKING_TIER_NAMES = {
    Decimal("1.0"): "Bronze",
    Decimal("2.5"): "Silver",
    Decimal("4.0"): "Gold",
    Decimal("6.0"): "Platinum",
    Decimal("7.5"): "Diamond",
}
