"""Versioned restaurant search and shortlist commands (more / closer / directions / reviews)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from app.domain import replies
from app.domain.commands import Routed
from app.domain.conflict import blocked_cuisines, build_plan
from app.domain.models import GeoPoint, RankedPlace, SearchPlan
from app.domain.parsing import CUISINE_TAGS
from app.domain.ranking import rank, select_shortlist
from app.persistence.repositories import ranked_from_row
from app.restaurants.base import ProviderError, ProviderRateLimited, ProviderTimeout
from app.restaurants.maps import maps_directions_url

if TYPE_CHECKING:
    from app.services.orchestration import Orchestrator

log = logging.getLogger("foodie.search")
POOL_SIZE = 15
ARRIVAL_LEAD_MINUTES = 20


class RecommendationService:
    def __init__(self, orch: Orchestrator) -> None:
        self.o = orch
        self.searched: set[str] = set()

    def plan_for(self, session, group, point: GeoPoint | None) -> SearchPlan:
        cons = [s.constraint for s in self.o.repo.constraints(session["id"])]
        return build_plan(
            cons, location=point,
            default_radius=group["default_radius_miles"] or self.o.s.default_radius_miles,
            max_radius=self.o.s.max_radius_miles,
        )

    async def run_search(self, group_id: str, session_id: str, version: int) -> None:
        start = time.perf_counter()
        try:
            await self._run(group_id, session_id, version)
        except asyncio.CancelledError:
            self.o.metrics.incr("search_cancelled")
            raise
        except Exception:
            log.exception("search job failed")
            self.o.repo.revert_to_collecting(session_id, version)
        finally:
            self.o.metrics.observe("search_job_total", time.perf_counter() - start)

    async def _fail(self, group, session_id: str, version: int, text: str) -> None:
        if self.o.repo.revert_to_collecting(session_id, version):
            await self.o.reply(group["chat_guid"], text, session_id, version)
        else:
            self.o.metrics.incr("stale_discarded")

    async def _run(self, group_id: str, session_id: str, version: int) -> None:
        o = self.o
        group, session = o.repo.group(group_id), o.repo.session(session_id)
        if not group or not session:
            return
        name = o.name(group)
        point: GeoPoint | None = None
        try:
            if session["lat"] is not None:
                point = GeoPoint(session["lat"], session["lon"], session["location_label"] or "shared location")
            elif session["location_label"]:
                with o.metrics.timed("geocode"):
                    point = await o.geocoder.geocode(session["location_label"])
                if not point:
                    o.repo.set_session_location(session_id, None, None, None)
                    await self._fail(group, session_id, version, f"I couldn't find \"{session['location_label'][:40]}\". Try a city name or a Maps link.")
                    return
                o.repo.set_session_coords(session_id, version, point.lat, point.lon, session["location_label"])
            elif group["default_lat"] is not None:
                point = GeoPoint(group["default_lat"], group["default_lon"], group["default_city"])
        except ProviderError as e:
            await self._fail(group, session_id, version, f"The map lookup is unavailable right now ({_kind(e)}). Say \"{name} go\" to retry.")
            return
        if point is None:
            await self._fail(group, session_id, version, "What area should I search?")
            return

        plan = self.plan_for(session, group, point)
        arrival = plan.arrival or (o.local_now() + timedelta(minutes=ARRIVAL_LEAD_MINUTES))
        tags: set[str] = set()
        for c in plan.all_cuisines:
            tags |= CUISINE_TAGS.get(c, frozenset({c}))
        notes: list[str] = []
        try:
            places = await self._search(point, plan.radius_miles, tags)
            with o.metrics.timed("ranking"):
                pool, excluded = rank(places, plan, arrival)
            # Broaden once, only when results are insufficient and the radius isn't strict.
            if len(pool) < 3 and not plan.radius_strict and plan.radius_miles < o.s.max_radius_miles:
                wider = min(o.s.max_radius_miles, plan.radius_miles * 2)
                more = await self._search(point, wider, tags)
                wplan = dataclasses.replace(plan, radius_miles=wider)
                wpool, wexcluded = rank(places + more, wplan, arrival)
                if len(wpool) > len(pool):
                    notes.append(f"I widened the search to {wider:g} miles to find more options.")
                    plan, pool, excluded = wplan, wpool, wexcluded
        except (ProviderError, asyncio.TimeoutError) as e:
            await self._fail(group, session_id, version, f"Restaurant lookup is unavailable right now ({_kind(e)}). Say \"{name} go\" to try again.")
            return

        for cuisine, avoid in blocked_cuisines(plan):
            notes.append(f"{cuisine.title()} is out because someone can't have {avoid}. Whoever wanted {cuisine}, name another cuisine and I'll redo the list.")
        shortlist = select_shortlist(pool, plan)
        try:
            alt = await self._diet_alternative(point, plan, arrival, shortlist)
        except (ProviderError, asyncio.TimeoutError):
            alt = None  # optional extra; the main shortlist still goes out
        if alt:
            shortlist.append(alt)
            diets = ", ".join(sorted(d.replace("_", "-") for d in plan.dietary))
            notes.append(f"Option {len(shortlist)} lists {diets} but isn't the cuisine you asked for.")
        if plan.budget_hard is None and plan.budget_soft is not None and all(r.place.price_level is None for r in shortlist):
            notes.append(f"Prices aren't listed, so I can't confirm the ${plan.budget_soft:g} budget.")
        if not shortlist:
            await self._fail(group, session_id, version, replies.no_results(plan, excluded, name))
            return
        stored = pool[:POOL_SIZE] + [r for r in shortlist if r not in pool[:POOL_SIZE]]
        slv = o.repo.store_pool_and_shortlist(session_id, version, stored, [r.place.provider_place_id for r in shortlist])
        if slv is None:
            o.metrics.incr("stale_discarded")
            log.info("discarded stale search result version=%d", version)
            return
        if session_id in o.votes_cleared:
            o.votes_cleared.discard(session_id)
            notes.insert(0, "Requirements changed, so earlier votes were cleared. Please vote again.")
        header = self._summary(plan, point, updated=session_id in self.searched)
        self.searched.add(session_id)
        text = header + "\n" + replies.shortlist(name, shortlist, plan, o.places.attribution, notes)
        await o.reply(group["chat_guid"], text, session_id, version)

    async def _diet_alternative(self, point: GeoPoint, plan: SearchPlan, arrival, shortlist: list[RankedPlace]) -> RankedPlace | None:
        """When a cuisine filter leaves every option with an unverified dietary need, offer the best
        place nearby whose listing does verify it, even if it's a different cuisine."""
        diets = {d.replace("_", "-") for d in plan.dietary}
        if not diets or not plan.all_cuisines or not shortlist or not all(diets & set(r.unverified) for r in shortlist):
            return None
        anything = dataclasses.replace(plan, cuisines_by_member={m: set() for m in plan.cuisines_by_member}, conflict="none")
        pool, _ = rank(await self._search(point, plan.radius_miles, set()), anything, arrival)
        shown = {r.place.provider_place_id for r in shortlist}
        return next((r for r in pool if not diets & set(r.unverified) and r.place.provider_place_id not in shown), None)

    async def _search(self, point: GeoPoint, radius: float, tags: set[str]):
        start = time.perf_counter()
        try:
            return await asyncio.wait_for(self.o.places.search(point, radius, tags), timeout=self.o.s.places_timeout_seconds + 5)
        finally:
            self.o.metrics.observe("search", time.perf_counter() - start)

    @staticmethod
    def _summary(plan: SearchPlan, point: GeoPoint, updated: bool) -> str:
        bits = []
        if plan.all_cuisines:
            bits.append(" / ".join(sorted(plan.all_cuisines)))
        for d in sorted(plan.dietary):
            bits.append(f"{d.replace('_', '-')} required")
        if plan.allergies:
            bits.append("allergy: " + ", ".join(sorted(a.replace("_", " ") for a in plan.allergies)))
        if plan.avoid:
            bits.append("avoiding " + ", ".join(sorted(plan.avoid)))
        if plan.budget_hard is not None:
            bits.append(f"${plan.budget_hard:g} max")
        elif plan.budget_soft is not None:
            bits.append(f"under ${plan.budget_soft:g}")
        where = point.label.split(",")[0]
        lead = "Updated" if updated else "Got it"
        return f"{lead}: {', '.join(bits) + ', ' if bits else ''}within {plan.radius_miles:g} mi of {where}."

    # ---- shortlist commands -----------------------------------------------------------------
    async def shortlist_command(self, group, session, routed: Routed) -> str:
        o, name, chat = self.o, self.o.name(group), group["chat_guid"]
        if not session or session["status"] not in ("shortlist", "voting"):
            await o.reply(chat, f"There's no current shortlist. Say \"{name} find dinner near <area>\" to start.")
            return "no_shortlist"
        current = o.repo.shortlist(session["id"])
        if routed.command in ("directions", "reviews"):
            n = int(routed.arg)
            row = next((r for r in current if r["option_number"] == n), None)
            if not row:
                await o.reply(chat, f"There's no option {n} on the current list.")
                return "bad_option"
            p = ranked_from_row(row).place
            if routed.command == "directions":
                await o.reply(chat, f"Directions to {p.name} from wherever you are: {maps_directions_url(p.latitude, p.longitude)}")
                return "directions"
            await o.reply(chat, f"I don't have review text for {p.name} from {o.places.name}, and I won't make any up. The Maps link shows public reviews: {p.maps_url}")
            return "reviews_unavailable"

        pool = [ranked_from_row(r) for r in o.repo.pool(session["id"])]
        shown = {r["place_id"] for r in current}
        if routed.command == "more":
            last_rank = max((r["rank"] for r in current), default=0)
            nxt = [r for r, row in zip(pool, o.repo.pool(session["id"]), strict=True) if row["rank"] > last_rank and r.place.provider_place_id not in shown][:3]
            if not nxt:
                await o.reply(chat, f"That's everything I found that fits. Say \"{name} radius 10\" to look wider.")
                return "more_exhausted"
            picked = nxt
        else:
            picked = sorted(pool, key=lambda r: (len(r.unverified), r.distance_miles))[:3]
            if {r.place.provider_place_id for r in picked} == shown:
                await o.reply(chat, "These are already the closest options that fit.")
                return "closer_same"
        o.repo.reassign_shortlist(session["id"], [r.place.provider_place_id for r in picked])
        session = o.repo.session(session["id"])
        plan = self.plan_for(session, group, None)
        text = replies.shortlist(name, picked, plan, o.places.attribution, ["New option numbers; earlier votes were cleared."])
        await o.reply(chat, text, session["id"], session["version"])
        return routed.command or "shortlist"


def _kind(e: BaseException) -> str:
    if isinstance(e, (ProviderTimeout, asyncio.TimeoutError)):
        return "timed out"
    if isinstance(e, ProviderRateLimited):
        return "rate limited"
    return "service unavailable"


__all__ = ["RecommendationService", "RankedPlace"]
