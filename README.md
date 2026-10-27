# Foodie AI

**An on-demand AI restaurant assistant for iMessage group chats.**

Foodie AI helps friends agree on where to eat without opening another app. It looks at group preferences, location, travel time, restaurant information, and budget, then suggests a short list with Google Maps links. Every group can vote to rename its assistant and choose its personality.

> **Project status: working offline MVP; live iMessage not yet tested.** The backend runs and is tested locally with mock messaging and a real OpenStreetMap snapshot. Blue-bubble delivery depends on a separately registered iMessage identity and an unofficial macOS bridge. No official Apple group-chat bot API is available for this use case.

| Area | Status |
|---|---|
| Backend: FastAPI, SQLite, sessions, onboarding, privacy, ranking, voting | Implemented; 123 automated tests pass |
| Offline demo with no Apple hardware or API keys (`python scripts/demo.py`) | Runs end to end |
| Live geocoding (Nominatim) | Verified once against the live service |
| Live restaurant search (Overpass) | Verified once against the live service (19 burger places near Tempe; the public server took ~30 s) |
| Jev decision adapter | Tested with simulated responses only; no credentials yet |
| BlueBubbles / real iMessage round trip | Tested with simulated responses only; **blocked** until the bot account and BlueBubbles are set up |

Full specification and acceptance criteria: [docs/spec.md](docs/spec.md). Build notes and measurements: [docs/implementation-log.md](docs/implementation-log.md). Mac, BlueBubbles and Jev setup: [docs/mac-setup.md](docs/mac-setup.md).

## Why build this?

Picking a restaurant with friends can turn into a long group chat. Some people want different cuisines, some have strict budgets or dietary needs, and others are traveling from different places. Foodie AI tries to find the best options for **everyone**, without choosing for them.

## Main features

- **Works in a blue-bubble iMessage group:** uses Messages on a Mac + BlueBubbles; no SMS fallback intended.
- **On demand:** wake the assistant by its group nickname or `Foodie AI`. It ignores unrelated dormant conversations at the application layer.
- **Group-controlled identity:** people vote on the assistant's nickname and personality.
- **Live nearby restaurant search:** use a confirmed city/area, current requested search radius, and real location listings.
- **Better suggestions:** consider operating hours at expected arrival, dietary evidence, budget and distance; ratings, review counts and prices when the provider has them (OpenStreetMap usually doesn't). Travel times are not implemented yet; distances are straight-line.
- **Maps links:** send a Google Maps listing link for each option, plus directions when possible.
- **Fair group decisions:** explain compromises and let each group member vote once.
- **Safe interruptions:** changing the cuisine, budget, or radius invalidates stale search results.
- **Privacy by design:** group activation, minimal session context, explicit opt-in to remembered preferences, and deletion commands.

## Demo conversation (storyboard; not live data)

> **Alex:** Foodie AI, find us dinner near Tempe. Under $25.  
> **Foodie AI:** Any must-have dietary restrictions? I'll use a five-mile radius for now.  
> **Sam:** Halal for me.  
> **Mike:** No sushi please.  
> **Foodie AI:** I'll filter out sushi and prioritize places with verifiable halal options. If I can't verify that, I'll say so.  
> **Foodie AI:** Here are three options, with rating/review count if available, expected hours, estimated travel and Maps links. Want to vote?  
> **Alex:** Foodie AI vote 2.  
> **Sam:** Foodie AI, closer than that.  
> **Foodie AI:** I'll narrow the search and refresh the shortlist before counting more votes.

The actual recommendations must come from a restaurant provider. Foodie AI must never invent restaurant names, prices, ratings, or dietary certifications.

## System architecture

![Local MVP architecture](docs/architecture.png)

**Flow:** iMessage group → macOS Messages / BlueBubbles → Python app → Jev (only when needed) + restaurant lookup + SQLite → filtered/ranked suggestions → iMessage.

- **BlueBubbles:** bridge between Messages and local Python backend. For safety, the project does **not** require disabling macOS SIP.
- **Python API:** wake-word detection, sessions, deduplication, interruption handling, and recommendation ranking.
- **Jev API:** hosted structured decision service for ambiguous intent, group conflicts and next-action decisions. Not a restaurant database. API access or usage may cost money; a rules-only fallback keeps the local prototype usable without a paid Jev call.
- **Restaurant provider:** OpenStreetMap / Overpass for a low-cost prototype. Coverage, reviews, prices, and hours may be incomplete. Add a licensed provider later for richer real-time data.
- **SQLite:** group preferences (opt-in), session state, personality votes, restaurant references, and voting.

**Performance approach:** deterministic commands first, call Jev only for ambiguity, query restaurants only when area and constraints are known, fetch extra details only for finalists, deduplicate events, and reject outdated search versions. Measure p50/p95 latency instead of promising a fixed response time.

## Entity-relationship design

![Entity relationship diagram](docs/er.png)

The major relationships are:

| Relationship | Meaning |
|---|---|
| Group → Members | One group has many members |
| Group → Sessions | A group can plan multiple meals over time |
| Member → Preferences | A member can opt in to saving several preferences |
| Session → Constraints | Each meal can have temporary limits and preferences |
| Session → Recommendations | One session has a ranked restaurant shortlist |
| Session + Member → Votes | Each participant can cast one current vote in a session |
| Group → Personality polls | A group can hold multiple naming/personality votes |
| Personality poll → Votes | One choice per participating member per poll |

See [docs/data-model.md](docs/data-model.md) for keys, data retention, and a Mermaid ER diagram that renders directly on GitHub.

## Session lifecycle

![Session lifecycle](docs/session.png)

- **Dormant:** only explicit wake-word messages are handled by the app; unrelated messages are discarded before any Jev request.
- **Collecting:** gather the requested area, restrictions, cuisine, budget and participant preferences.
- **Searching:** retrieve nearby candidates and rank them. Session versioning rejects outdated searches.
- **Shortlist:** show three options with sourced details, caveats and map links.
- **Voting:** one vote per member, with updates until the poll closes.
- **Done:** stop, timeout, or final decision; purge temporary message content according to the retention policy.

## User stories & storyboards

See **[docs/user-stories.md](docs/user-stories.md)** for primary flows, message-by-message storyboards, acceptance criteria, and tricky edge cases: naming the bot, starting a food session, changing plans mid-search, conflicts, adding a late participant, voting, safety requirements, and offline recovery.

## Data and privacy rules

1. Only allow configured/consenting group IDs to use the bot.
2. Messages reach macOS / BlueBubbles as a technical necessity. **Dormant does not mean Messages or the bridge cannot receive them.** The Foodie application should not store or send unrelated messages to Jev.
3. During an explicitly active session, forward only necessary, relevant messages to Jev. Clearly inform participants that Jev is a hosted service.
4. Persist food preferences only after an individual opt-in. `Foodie AI forget me` removes that member's saved profile.
5. Anyone can say `Foodie AI stop` to end a session. Expire idle sessions, for example after 10 minutes.
6. A person cannot change another member's hard allergy or dietary requirement.
7. Don't present third-party menu/allergy/halal claims as verified unless the available evidence truly supports them.
8. Keep credentials in environment variables and out of the repository. Avoid disabling macOS SIP.

## Local development plan

### Quickstart (offline, no credentials)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip "setuptools>=68" wheel   # Python 3.10's bundled setuptools can't do editable installs
pip install -e '.[dev]'
cp .env.example .env
pytest -q
python scripts/demo.py
uvicorn app.main:app --host 127.0.0.1 --port 5050
```

Keep the repo out of iCloud-synced folders (like an optimized Desktop); otherwise imports can hang while files re-download.

**Hardware:** an existing Intel Mac. BlueBubbles and Messages must run under the dedicated bot's iMessage identity (a separate Apple Account email may be used if activation succeeds).

**Requirements for re-rendering the design diagrams:** Python, the [Diagrams](https://diagrams.mingrammer.com/docs/getting-started/examples) package, and Graphviz. The architecture source is provided in [`diagrams/architecture.py`](diagrams/architecture.py).

```bash
# On macOS with Homebrew
brew install graphviz
python3 -m venv .venv
source .venv/bin/activate
pip install diagrams
python diagrams/architecture.py
```

Do not add API keys to this repository; they belong in `.env`, which Git ignores.

### Milestones

1. Verify an independent bot Apple Account can send/receive blue-bubble iMessages in a test group. **Not done yet** (see [docs/mac-setup.md](docs/mac-setup.md)).
2. Build a local webhook listener and deterministic `Foodie AI help` / `stop` commands. **Done.**
3. Save group configuration and active sessions in SQLite; add nickname/personality voting. **Done.**
4. Add Jev integration with strict input filtering and a rules-only fallback. **Done; live call not yet tested.**
5. Add area geocoding, live restaurant lookup, radius filtering and Maps links. **Done; live Overpass verified once.**
6. Add fairness-aware ranking, valid voting, stale-result protection and automated tests. **Done.**
7. Benchmark performance and record a consent-based demo before cloud scaling. **Offline benchmark done; live demo pending.**

## Future scaling

Keep the Mac as a replaceable **message gateway**, not the decision engine. Later migrate the Python backend to a hosted service, SQLite to PostgreSQL, and restaurant data to a richer licensed provider. An actual blue-bubble bridge would still require an accessible real macOS Messages session, even if the rest runs in the cloud.

## Tools and references

- [Diagrams — examples](https://diagrams.mingrammer.com/docs/getting-started/examples)
- [Diagrams — installation](https://diagrams.mingrammer.com/docs/getting-started/installation)
- [BlueBubbles](https://bluebubbles.app/)
- [BlueBubbles API and webhooks](https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks)
- [OpenStreetMap](https://www.openstreetmap.org/)
- [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [Google Maps URLs](https://developers.google.com/maps/documentation/urls/guide)

## License

No license selected yet. Add a `LICENSE` file before allowing reuse of the code.
