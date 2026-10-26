# Codex execution instructions — Foodie AI

You are implementing the project specified in [README.md](README.md). The README is the authoritative scope, privacy contract, build order and acceptance test list.

1. **Implement, don't just propose.** Start with a working offline mock demo, tests and typed core; continue into actual adapters while clearly marking hardware/credential-dependent functionality unverified.
2. **Local-first and free by default.** Do not call paid APIs, enable Jev, send live iMessages, or turn on billable services without explicit user configuration. Use dependency injection and mocks for offline tests.
3. **No SIP changes, no SMS fallback, no background conversation surveillance.** The user requires a blue-bubble iMessage agent with on-demand processing and explicit group/user consent. Honor allowlists, wake words, stop, memory deletion and data minimization.
4. **Jev must be implemented.** Provider endpoint formats vary; check the actual user's provider docs and configure the request schema rather than assuming a universal endpoint. Add mocked contract tests and fail safely.
5. **Never fabricate restaurant fields.** Treat unknown reviews, hours, prices, travel times, safety claims as unknown and label them clearly. Honor public OSM rate limits.
6. **Stale results never send.** Use session versions, event dedupe, per-group locking, and state validation before outbox delivery. Test interruption, reboot and duplicate sends.
7. **Maintain code quality.** Typed Python, compact modules, lint/format, `pytest`, mocked network requests; no secrets or raw personal chat messages in repo or logs.
8. **Update docs and status accurately.** At each milestone run tests and record results in `docs/implementation-log.md`. Keep diagrams/docs consistent. No unsubstantiated latency claims.

Suggested first commands after checking environment: `python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]' && pytest -q && python scripts/demo.py`.

When blocked by live iMessage or Jev setup, keep the offline deliverable usable and report precisely what the user must configure. Do not fake a successful integration.
