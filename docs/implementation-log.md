# Implementation log

All results below were produced on the target machine: Intel Mac (x86_64), macOS Darwin 24.6.0,
Python 3.10.1 (the only Python installed; 3.11+ was not forced). Dates are 2026-10-26.

## Status summary

| Area | Status |
|---|---|
| Offline MVP (FastAPI, SQLite, mocks, sessions, ranking, voting, privacy) | **Done, tested** |
| Offline end-to-end demo (`scripts/demo.py`) | **Done, runs** |
| Live Nominatim geocoding adapter | **Verified once live** (Tempe, AZ resolved) |
| Live Overpass search adapter | **Verified live once (2026-10-26):** `live_osm_check.py "Tempe, AZ" burger` returned 19 real places within 2 mi. The public server took ~30 s, so the default `PLACES_TIMEOUT_SECONDS` is now 45 (earlier attempts at 20 s returned 502 or timed out). |
| Jev adapter (both documented schemas) | **Contract-tested with mocked HTTP; no live call** (no credentials, provider not yet confirmed) |
| BlueBubbles adapter | **Unit-tested with mocked HTTP; no live call** (no bot identity / server on this Mac yet) |
| iMessage round trip (US-01) | **Blocked**: requires the bot Apple Account + BlueBubbles setup in docs/mac-setup.md |
| Diagram PNG re-render | **Not done**: Graphviz is not installed; `.dot`/Mermaid sources updated, original PNGs preserved |

## Milestone 1: inspect environment

- Repo contained README, AGENTS, docs, diagrams; not a Git repository.
- `python3 --version` → 3.10.1. `dot` not installed. Network to PyPI/OSM available.
- Problem found: the Desktop is synced to iCloud Drive with storage optimization. Files in
  `.venv/` became "dataless" and Python imports blocked for minutes. Fix: virtualenv in
  `.venv.nosync/` (iCloud ignores `.nosync`), `.venv` symlink to it, and the local `.env` uses
  `DATABASE_URL=sqlite:///./data.nosync/foodie.db`. Recommended: move the project out of iCloud.
  Even so, the first server start took ~27 s while iCloud-backed source files were read.

## Milestone 2: scaffold

`pyproject.toml` (setuptools, ruff, pytest-asyncio auto mode), `.env.example`, typed domain models,
migration `001_initial.sql` (WAL, foreign keys, partial unique index for one active session per
group, `processed_events`, `outbox`, `audit_events`, `session_participants`), repositories, mocks.

Persistence choice: stdlib `sqlite3` with short synchronous transactions behind one lock, not
`aiosqlite`. Each statement is a sub-millisecond local write, so a thread hop per query would cost
more than it saves; per-group `asyncio.Lock`s sit above it. A PostgreSQL move replaces
`persistence/` only.

Offline fixture data: one Nominatim lookup each for Tempe and Mesa and one Overpass query per city
(restaurants, fast food, food courts within 5 mi) were saved, trimmed to name/coordinates/cuisine/
diet/hours/address/website tags: 1,196 real OSM elements, ODbL attribution kept in the file.
No rating, review or price fields exist in it, by design.

## Milestones 3-4: privacy, onboarding, state machine, idempotency, outbox

Admission order: self-sent → chat allowlist → wake word or active session → event dedupe →
per-group lock. Dormant non-wake messages leave no trace (no body, no event id, no call).
Onboarding is a persisted state machine with a conditional update so the intro is sent once,
even across duplicate webhooks, repeated setup commands and restarts. Group consent needs
`GROUP_CONSENT_MIN` explicit agreements; any decline stops participation.

Sessions: every requirement/location change increments `version`. Search jobs record their start
version; results are stored only if version and status still match (in one transaction), and the
outbox re-checks the live version again right before each send. Stop ends the session, discards
pending session messages and cancels jobs. On restart, in-flight searches expire, `sending` outbox
rows become `uncertain` (never resent automatically), and processed event IDs persist.

## Milestones 5-6: places, ranking, conflicts, voting, demo

Filtering order follows the spec ([spec.md](spec.md)). Unknown evidence for a hard requirement (halal, hard budget)
flags the candidate, and all flagged candidates rank below verified ones. Hours parser understands
common OSM syntax; anything else is "hours not confirmed". Ranking weights 30/20/20/15/15, with
reviews and price omitted (and weights renormalized) when the provider has no data; unknown hours
score neutral 0.5 and are labeled. Group satisfaction = 0.65 mean + 0.35 min. Cuisine conflicts
prefer a place satisfying several members, then one option per craving.

Found and fixed during the demo:
- `dedupe()` was O(n²) (~3 s for 600 places). Now bucketed by name: ranking p50 ≈ 24 ms.
- `forget me` also deleted what the member had said in the current session, causing a surprise
  re-search. It now deletes saved preferences and only session constraints derived from them.
- `Chef help us pick dinner` was routed to `help`; `help` now only matches the bare command.
- Webhook accepted loopback requests without a secret in development; it now always requires
  `BB_WEBHOOK_SECRET`, and BlueBubbles mode refuses to start without it.
- A cuisine fully excluded by someone's hard "avoid" (sushi vs no seafood) is now explained in
  the reply; a soft budget with no price data says it couldn't be confirmed.

## Milestones 7-8: Jev and BlueBubbles adapters

Jev: two schemas, selected explicitly with `JEV_SCHEMA` (no default, startup fails if missing).
One batched call with three `choice` questions; labels validated against enums; confidence
threshold; per-session and per-day call caps; no retries; 401/403 disables Jev for the process.
Jev is called only for ambiguous, food-related messages inside an active session.

BlueBubbles: send via `POST /api/v1/message/text?password=` with `tempGuid` = outbox id (the
server de-duplicates on it); webhook normalization for `new-message`; connect errors are retryable
(bounded to 2 attempts), read timeouts/5xx are "uncertain" and never resent. Endpoint/body taken
from the BlueBubbles Postman collection; webhook field names must be checked on the installed server.

## Milestone 9-10: tests, benchmark, docs

Commands executed (from the repo root):

```bash
python3 -m venv .venv.nosync && ln -s .venv.nosync .venv
.venv/bin/pip install --upgrade pip "setuptools>=68" wheel
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check app tests scripts        # All checks passed!
.venv/bin/pytest -q                           # 123 passed
.venv/bin/python scripts/demo.py              # full offline storyboard, 0 network calls
.venv/bin/python scripts/benchmark.py --sessions 40
.venv/bin/python scripts/live_osm_check.py "Tempe, AZ" burger   # geocode OK; Overpass OK with the 45 s timeout
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5050     # /health, /dev/simulate checked with curl
```

Test files: commands (11), privacy (13), onboarding (11), sessions (8), interruptions (10),
places (19), ranking (15), voting (10), jev (17), webhook (9) = 123 tests (parametrized cases counted).

### Benchmark (offline only; measured 2026-10-26T20:22Z, 40 sessions, 320 messages)

Mock messaging, OSM snapshot, rules decisions, debounce disabled so every requirement triggers a
search (worst case for search count). Not representative of public Overpass or iMessage latency.

| Stage | n | p50 ms | p95 ms |
|---|---|---|---|
| webhook admission + handling (`admission_total`) | 320 | 1.30 | 2.71 |
| search (snapshot provider) | 160 | 2.31 | 2.83 |
| ranking | 160 | 23.73 | 28.92 |
| search job total (geocode + search + rank + store + send) | 160 | 28.64 | 35.58 |
| send (mock) | 320 | 0.06 | 0.11 |

Jev requests/session: 0 (rules mode). Stale results discarded: 0 in this run (no interruptions
scripted; the demo run shows 1). Send failure rate: 0. Cache hit rate: n/a for the snapshot provider.

## Reply polish (2026-10-26)

Changes after reviewing the demo as a group-chat reader:

- Shortlists are one line per place plus its map link, with a single footer. Unverified requirements
  shared by every option are stated once ("Not verified for any option: budget").
- Distances under 0.1 mi show as "<0.1 mi" instead of "0.0 mi"; "straight-line" is said once.
- If every cuisine match has an unverified dietary need, the best nearby place whose OSM listing
  verifies it is added as a votable extra option (e.g. "4. The Halal Guys - not burger / sushi -
  lists halal").
- A cuisine ruled out by someone's hard avoid (sushi vs no seafood) now asks whoever wanted it to
  name another cuisine.
- 3 new tests in `tests/test_places.py`; `pytest -q`: 123 passed; `ruff check`: clean.

## Known limitations

- No live iMessage or Jev verification yet; live Overpass verified once (see status table).
- OSM has no ratings, reviews or prices; replies say so. Halal/allergy evidence is rarely tagged,
  so most candidates show "not verified". When a cuisine filter leaves every option with an
  unverified dietary need, one extra Overpass query (no cuisine filter) looks for a place that lists it.
- Opening hours: common syntax only; holidays ignored; timezone is one configured zone.
- Travel time is not computed (straight-line miles only, labeled as such).
- Custom personality text is stored but replies are deterministic templates; styles only tweak a
  few phrases.
- Members are identified by hashed handle; replies never name people because display names are
  not stored.
- Members who never said `agree` must start messages with the wake word to be heard.
- Single process, in-memory timers and locks: fine for one Mac, not for multiple workers.
