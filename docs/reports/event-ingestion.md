# Report: Event ingestion (P07) — 100k-row query measurement

Deliverable: "measure the list query with 100k rows and tell me the
timing." The script is `backend/scripts/measure_events_query.py`; it
creates and drops its own scratch database
(`sentinelx_measure_<hex>`) on the dev Postgres and seeds **100,000
security_events across 2 organizations (80k / 20k)**, spread over 7
days of timestamps, with the production index set from migration
`f7a8b9c0d1e2` plus the originals.

Run (2026-09-24, dev compose Postgres, local Windows workstation;
each query run 5x after a warmup, 50-row page):

| Query | min | median | max |
|---|---|---|---|
| Unfiltered first page (keyset) | 2.10 ms | **2.62 ms** | 3.34 ms |
| severity=high | 2.79 ms | **6.16 ms** | 7.42 ms |
| Time window (24h) | 2.66 ms | **2.75 ms** | 3.21 ms |
| Second page (keyset cursor) | 1.71 ms | **3.20 ms** | 4.24 ms |
| Free-text `q` (JSONB ilike) | 9.13 ms | **107.13 ms** | 109.69 ms |

EXPLAIN ANALYZE for the unfiltered first page: an index scan on
`ix_security_events_org_occurred_at_desc` (the `(organization_id,
occurred_at DESC)` index added by `f7a8b9c0d1e2`) with an incremental
sort for the `id` tiebreak — **0.077 ms execution time server-side**.
The remaining per-query wall time is Python/asyncpg round-trip, not
the database.

## Notes

- **Everything but free-text is index-served and single-digit
  milliseconds.** The severity filter's spread (2.8–7.4 ms) is the
  composite `(organization_id, severity, occurred_at)` index doing its
  job; the keyset second page never degrades with depth (no OFFSET).
- **Free-text is the one unindexed path** (~107 ms median): it ILIKEs
  over the JSONB text form of `normalized_data`/`raw_data`, which no
  B-tree serves. Acceptable for this milestone; if it becomes hot, the
  fix is a GIN trigram index over the payload text, not a schema
  change.
- Three seed-script bugs were fixed while measuring (each would have
  silently distorted a number): the `jsonb_to_recordset` alias is
  `"user"`, not `username` (`UndefinedColumnError`); `row_number()`
  needs its `OVER ()` clause; and the seeded JSONB built the key
  `'message'` twice, so the free-text probe matched 0 rows and
  "measured" an empty scan — the honest match now returns 50 rows.
  Datetime bind params were also fixed to pass real datetimes
  (asyncpg rejects their string forms).
