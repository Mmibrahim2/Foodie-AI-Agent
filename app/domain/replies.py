"""Concise deterministic reply templates. No emojis, no invented facts.

Personality only adjusts a few phrases; it never changes safety, privacy or data content.
"""

from __future__ import annotations

from app.domain.models import RankedPlace, SearchPlan

ALLERGY_CAVEAT = "Allergy safety can't be verified from listings; please confirm allergens and prep directly with the restaurant."


def _style(personality: str) -> str:
    return personality.split(":", 1)[0] if personality else "adaptive"


def ack(personality: str, text: str) -> str:
    style = _style(personality)
    if style == "chill":
        return text.replace("Got it.", "Cool, got it.")
    if style == "funny":
        return text.replace("Got it.", "Noted, chef's orders.")
    return text


def intro(name: str, jev_enabled: bool, places_live: bool, consent_min: int) -> str:
    jev = (
        "Some unclear messages during an active search are classified by the hosted Jev service (no names, numbers or chat history are sent)."
        if jev_enabled
        else "Message handling stays on this computer."
    )
    places = "Restaurant lookups use OpenStreetMap." if places_live else "Restaurant lookups use a saved OpenStreetMap snapshot."
    need = "" if consent_min <= 1 else f" I need at least {consent_min} of you to agree."
    return (
        f"Hi, I'm {name}, an AI assistant that helps pick restaurants. I only read messages that start with my name, "
        f"plus food-related replies while a search is active, and I don't read past history. {jev} {places} "
        f"Reply \"{name} agree\" to opt in or \"{name} decline\".{need}"
    )


def polls_open(name: str) -> str:
    return (
        f"Thanks. Two quick votes: what should this group call me? Reply \"{name} name Chef\" (or any name). "
        f"And my style: \"{name} style adaptive\", chill, funny, or direct. Say \"{name} close vote\" when done."
    )


def ask_city(name: str) -> str:
    return f"What's the usual city or neighborhood for food? Reply \"{name} city Tempe, AZ\" or \"{name} skip city\". I won't save it until you confirm."


def confirm_city(name: str, label: str, radius: float) -> str:
    return f"I found {label}. Save it as the default with a {radius:g}-mile radius? Reply \"{name} confirm\" or \"{name} radius 3\"."


def setup_done(name: str) -> str:
    return f"All set. Say \"{name}\" when you want food ideas, \"{name} help\" for commands."


def help_text(name: str) -> str:
    return (
        f"Start: \"{name} find dinner near Tempe under $20\". During a search just say needs like \"halal\", \"no seafood\", \"5 miles max\". "
        f"Then \"{name} vote 1\", \"{name} more\", \"{name} closer\", \"{name} directions 2\". "
        f"Also: \"{name} stop\", \"{name} privacy\", \"{name} forget me\"."
    )


def privacy_text(name: str, jev_enabled: bool) -> str:
    jev = "Jev is enabled for unclear messages during active searches (redacted, no history)." if jev_enabled else "Jev is off; nothing is sent to an AI service."
    return (
        "I ignore messages that don't start with my name unless a search is active. I never store message text. "
        "During a search I keep structured needs (like budget or diet) until it ends. "
        f"Saved preferences exist only if you asked me to remember them. {jev} "
        f"\"{name} forget me\" deletes your saved data; organizers can use \"{name} erase group\"."
    )


def _miles(d: float) -> str:
    return f"{d:.1f} mi straight-line"


def shortlist(name: str, ranked: list[RankedPlace], plan: SearchPlan, attribution: str, notes: list[str]) -> str:
    lines = ["Best matches I found:" if len(ranked) > 1 else "Best match I found:"]
    for i, r in enumerate(ranked, start=1):
        p = r.place
        bits = [p.name]
        if p.rating is not None and p.review_count:
            bits.append(f"{p.rating:.1f} stars ({p.review_count} reviews)")
        bits.append(_miles(r.distance_miles))
        if p.price_level:
            bits.append("$" * p.price_level)
        lines.append(f"{i}. " + " - ".join(bits))
        detail = [r.hours_note]
        if r.reasons:
            detail.append("Why: " + "; ".join(r.reasons[:2]))
        lines.append("   " + ". ".join(detail) + ".")
        if r.unverified:
            lines.append("   Not verified: " + ", ".join(r.unverified) + " (check with the restaurant).")
        lines.append(f"   Map: {p.maps_url}")
    if plan.allergies:
        lines.append(ALLERGY_CAVEAT)
    lines.extend(notes)
    lines.append("No ratings or prices in this data source." if all(r.place.rating is None for r in ranked) else "")
    lines.append(f"Reply \"{name} vote 1\", \"{name} more\", or \"{name} closer\". {attribution}.")
    return "\n".join(ln for ln in lines if ln)


def no_results(plan: SearchPlan, excluded: dict[str, int], name: str) -> str:
    reasons = []
    if excluded.get("dietary"):
        reasons.append("listings that say they don't meet a dietary need")
    if excluded.get("closed"):
        reasons.append("places closed at that time")
    if excluded.get("budget"):
        reasons.append("places over the hard budget")
    if excluded.get("cuisine") or excluded.get("avoid"):
        reasons.append("cuisine mismatches")
    why = f" after removing {', '.join(reasons)}" if reasons else ""
    return (
        f"I couldn't find a verified match within {plan.radius_miles:g} miles{why}. "
        f"I won't relax anyone's hard requirements on my own. You can widen the area (\"{name} radius 10\"), "
        f"change the cuisine, or the person who set a requirement can say \"{name} drop my budget\"."
    )
