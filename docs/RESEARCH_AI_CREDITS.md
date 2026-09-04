# Research AI credits

Credits express recorded provider cost in a customer-facing unit. The initial
scale is **1,000 credits per USD** of provider cost, defined by
`CREDITS_PER_USD` in `src/research_ai/services/credit_service.py`. This is a display
conversion, not a new payment balance, markup, or fixed charge per message.
The existing cost ledger and budget policies remain authoritative.

## Usage meter

`GET /api/research_ai/usage-budget/` includes:

```json
{
  "credits": {
    "daily_limit": "250",
    "used": "1.65",
    "remaining": "248.35"
  }
}
```

Render the credit fields for customers, for example **248.35 credits remaining**.
Existing dollar fields remain available for compatibility. `resets_at` describes
the UTC daily reset. Amounts are decimal strings, and fractional credits are
preserved. `null` for the limit and remaining means unlimited; zero means zero.
Remaining credits stop at zero if usage exceeds the allowance.

Notebook chat uses the existing usage ledger and daily budget enforcement.
The default per-turn iteration ceiling is removed; the daily budget policies
still apply. Historical notebook calls that predate accounting are not backfilled.
The meter covers recorded usage across features, not just one notebook.

## Model picker

`GET /api/research_ai/models/` includes a `multiplier` and `credit_rates` on each
model, plus a top-level `credit_pricing` object explaining the comparison:

```json
{
  "credit_pricing": {
    "multiplier_base_model": "openrouter:deepseek/deepseek-v4-flash-0731",
    "multiplier_basis": "equal_input_output_tokens",
    "multiplier_is_estimate": true
  }
}
```

Use picker labels such as **DeepSeek V4 Flash · 1×** and
**DeepSeek V4 Pro · ~12.6×**. Suggested tooltip:
“Estimated relative credit usage. Actual usage depends on input and output length,
caching, and model-provided searches.”

The baseline is fixed so adding a cheaper model does not silently change every
other model's multiplier. Multipliers compare equal quantities of uncached input
and output tokens, rounded to one decimal place. They are not per-message prices.

`credit_rates` contains decimal strings for:

- `input_per_million_tokens`
- `output_per_million_tokens`
- `cache_read_per_million_tokens`
- `cache_write_per_million_tokens`
- `web_search_per_request`

Models with conditional pricing also include `long_context`, with a
`prompt_tokens_above` threshold and replacement token `credit_rates`. These rates
apply when input plus cache-read and cache-write tokens strictly exceed the
threshold; the search rate stays unchanged.

Rates use the same reviewed pricing table as the ledger and are estimates.
Provider-reported costs take precedence when available. Otherwise, usage sums
each token bucket times its applicable rate, plus reported model-provided search
charges. The ledger rounds each provider response to integer micro-USD before
conversion to credits. The displayed multiplier is never applied again to the
charge. Separate tool integrations are not included in these model rates.

An unpriced model has `null` rates and multiplier; render “Pricing unavailable”,
not zero or free. Usage without reviewed pricing or a provider-reported cost
retains a null cost in the ledger and is excluded from known-spend totals.
The `allowed` field continues to describe model access.
