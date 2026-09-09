# Withdrawal nonce safety

Withdrawals and revenue burns use `HotWalletService` to reserve nonces. A shared
PostgreSQL transaction lock serializes reservation for each chain and sender.
Reservations have a case-insensitive unique constraint on chain, sender and nonce.
The reservation commits before the network call. Once reserved, an operation is
never automatically resubmitted or refunded after an uncertain response.

The RPC's pending nonce must be at least its confirmed count and greater than
every recorded reservation and legacy withdrawal nonce for that wallet. Stale
responses stop submission and produce an error event. Existing withdrawal rows,
including failed and soft-deleted rows, remain part of this check. Historical
duplicate rows do not need to be rewritten to apply the migration.

Burns commit their ledger debit with the nonce reservation. A failed or uncertain
burn needs manual reconciliation; a network error no longer rolls that debit back.

## Deployment

1. Pause withdrawal and burn broadcasts, and drain existing jobs. Old workers
   bypass the reservation service, so do not run mixed worker versions for sends.
2. Apply reputation migration `0121_hot_wallet_nonce_reservation`.
3. Deploy/restart every worker that sends hot-wallet transactions or checks pending
   withdrawals. Route operational scripts through the same service.
4. Resume broadcasts and the existing five-minute pending-withdrawal checker.
5. Confirm the existing Sentry error-event notification rule includes
   `reputation.services.hot_wallet_service` and
   `reputation.services.withdrawal_recovery_service` events. This change uses the
   existing production Sentry integration; it does not configure Sentry rules.

The checker reports withdrawals pending more than ten minutes on its next run,
so detection normally occurs within ten to fifteen minutes. It uses reservation
creation time, or withdrawal creation time for legacy records, rather than
`updated_date`. Each unresolved withdrawal produces at most one stale alert per
hour. Recent checks do not reset its age or modify `updated_date`.

## Manual reconciliation

Inspect the withdrawal, its `nonce_reservation`, and the chain's transaction and
receipt for the saved hash and sender/nonce. The reservation records the intended
recipient, amount, submission hash when available, and last submission error.
An empty hash does **not** prove that nothing was sent.

- Confirm the correct recipient, token and amount before marking a payment paid.
- If the nonce was used by another transaction, reconcile that payment before
  releasing the affected withdrawal's debit.
- If submission remains uncertain, keep funds held. A timeout or retry limit is
  not proof of failure.
- A reservation for an unused nonce intentionally prevents automatic reuse. A
  stuck nonce must be resolved on chain under operator control before subsequent
  broadcasts can proceed. Do not delete reservations or reset their nonce simply
  to bypass the check.
- Marking a withdrawal failed releases its existing ledger debit through the
  balance calculation. Do not also create a refund credit.

The checker re-reads status under a row lock and respects manual terminal status
changes. It only retries rows with no hash, nonce or reservation. Receipt-based
confirmation remains active for transactions with a known hash.

Do not roll back to the old broadcasting code while unresolved reservations or
in-flight transfers exist. Pause sends and reconcile first; dropping the new
table removes the persistent protection and audit history.
