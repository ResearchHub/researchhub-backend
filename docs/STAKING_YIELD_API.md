# Staking Yield API

## Overview
The Staking Yield API allows authenticated users to retrieve details about ResearchCoin (RSC) earned through staking. Yield is accrued daily based on each user's proportion of the total weighted stake.

## Endpoints

### 1. Get Staking Yield Details

**Endpoint**: `GET /api/staking_yield/details/`

**Authentication**: Required

**Description**: Returns the authenticated user's current staking position and lifetime yield summary.

#### Response

```json
{
    "is_staking_opted_in": true,
    "staking_opted_in_date": "2026-04-15T00:00:00Z",
    "current_stake": "50000.00000000",
    "current_multiplier": "1.00000000",
    "current_weighted_stake": "50000.00000000",
    "total_yield_earned": "1234.56789012",
    "latest_accrual_date": "2026-04-20"
}
```

#### Response Fields

| Field | Type | Nullable | Description |
|---|---|---|---|
| `is_staking_opted_in` | boolean | No | Whether the user has opted into staking. |
| `staking_opted_in_date` | datetime | Yes | Timestamp of when the user opted into staking. `null` if the user has never opted in. |
| `current_stake` | decimal | No | The user's RSC stake amount from the most recent daily snapshot. `0` if no snapshots exist. |
| `current_multiplier` | decimal | No | The staking multiplier applied to the user's stake based on the age of their remaining unlocked balance lots, clipped by how long they have been opted into staking. `0` if no snapshots exist. |
| `current_weighted_stake` | decimal | No | The user's effective stake after applying the multiplier (`current_stake * current_multiplier`). Used to determine their share of daily yield. `0` if no snapshots exist. |
| `total_yield_earned` | decimal | No | Cumulative RSC earned from staking across all accrual dates. `0` if no yield has been accrued. |
| `latest_accrual_date` | date | Yes | The date of the most recent daily snapshot that includes this user. `null` if no snapshots exist. |

---

### 2. Get Yield Earned Since Date

**Endpoint**: `GET /api/staking_yield/earned_since/?date=YYYY-MM-DD`

**Authentication**: Required

**Description**: Returns the total RSC yield the authenticated user has earned on or after the specified date.

#### Query Parameters

| Parameter | Required | Format | Description |
|---|---|---|---|
| `date` | Yes | `YYYY-MM-DD` | The start date (inclusive) from which to sum yield. |

#### Response

```json
{
    "since_date": "2026-04-15",
    "yield_earned": "456.78901234"
}
```

#### Response Fields

| Field | Type | Description |
|---|---|---|
| `since_date` | date | The date that was provided in the query parameter. |
| `yield_earned` | decimal | Total RSC earned from staking on or after `since_date`. `0` if no yield has been accrued in that period. |

#### Error Responses

| Status | Condition | Body |
|---|---|---|
| 400 | `date` query parameter is missing | `{"error": "Query parameter 'date' is required (YYYY-MM-DD)."}` |
| 400 | `date` value is not a valid date | `{"error": "Invalid date format. Use YYYY-MM-DD."}` |
| 401 | Request is not authenticated | Standard DRF authentication error |

## Staking Opt-In

Before a user can earn yield, they must opt into staking via the User API.

### Toggle Staking Opt-In

**Endpoint**: `PATCH /api/user/set_staking_opted_in/`

**Authentication**: Required

**Description**: Opts the authenticated user into or out of staking. When a user opts in, their available RSC balance is included in the next daily snapshot and begins earning yield. When they opt out, they are excluded from future snapshots and stop accruing yield.

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `is_staking_opted_in` | boolean | Yes | `true` to opt in, `false` to opt out. |

#### Behavior

- **Opting in** (`true`): Sets `is_staking_opted_in` to `true` and records the current timestamp in `staking_opted_in_date`. The user's full available (unlocked) RSC balance is treated as their stake starting from the next daily snapshot. Existing balance only receives age-based multiplier credit from the opt-in date forward.
- **Opting out** (`false`): Sets `is_staking_opted_in` to `false` and clears `staking_opted_in_date` to `null`. The user is excluded from future snapshots and stops earning yield. Previously earned yield is not affected.
- **Idempotent**: Opting in when already opted in does not reset `staking_opted_in_date`.

#### Response

Returns the full serialized User object.

#### Eligibility

Even after opting in, a user is excluded from daily snapshots if any of the following are true:
- `is_active` is `false`
- `is_suspended` is `true`
- `probable_spammer` is `true`

---

## How Staking Yield Works

1. A daily Celery task creates a **global snapshot** that records the circulating RSC supply and aggregates all opted-in users' stakes.
2. Each opted-in user gets a **user snapshot** within that global snapshot, capturing their stake amount and multiplier at that point in time.
3. A second task computes each user's share of the daily emission and writes a **yield record** linked to their snapshot. The yield is distributed as locked RSC balance.
4. Daily emission follows a halving schedule: starting at 9,500,000 RSC/year, halving every 64 years. A user's daily yield is proportional to their weighted stake relative to the total weighted stake.
5. The staking multiplier uses the step schedule `0-29d = 1.0x`, `30-179d = 1.05x`, `180-364d = 1.1x`, `365+d = 1.25x`. A user's snapshot stores their own multiplier and weighted stake, and the global snapshot denominator is derived from the weighted positions of all opted-in staked users.

## Related Code

- Opt-in endpoint: `src/user/views/user_views.py` (`set_staking_opted_in`)
- User model staking fields: `src/user/related_models/user_model.py` (`is_staking_opted_in`, `staking_opted_in_date`)
- Yield view: `src/reputation/views/staking_yield_view.py`
- Serializers: `src/reputation/serializers/staking_yield_serializer.py`
- Service: `src/reputation/services/staking_yield_service.py`
- Models: `src/reputation/related_models/staking_global_snapshot.py`, `staking_user_snapshot.py`, `staking_yield_record.py`
- Tests: `src/reputation/tests/test_staking_yield_views.py`
