"""Preferences that do not come from a form field.

Three sources feed the ranking besides the explicit chips:

* **Scene cards**: pictures the traveller picks when they have no interests
  to name. Each card maps to catalogue themes.
* **Past-trip answers**: "Best moment on your last Japan trip?" and "What
  tired you?". The service asks the LLM to extract structured preferences
  (``PastTripPreferences``); ``keyword_past_trip`` is the deterministic
  extractor used offline and whenever the model call fails.
* **Reactions** on option cards: "More like this", "Quieter", "More
  unexpected", "Not for me".

All of them end up as a ``Preferences`` object of plain weights the scorer
reads. Nothing here can create a destination or a fact; it only re-weights
places already in the catalogue.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from jst_api.domain.enums import Interest
from jst_api.planner.model import MAX_INTERESTS, Avoid, Conditions, ReactionKind


@dataclass(frozen=True)
class SceneCard:
    slug: str
    title: str
    themes: tuple[str, ...]


SCENE_CARDS: tuple[SceneCard, ...] = (
    SceneCard("snowy-onsen-town", "Snowy onsen town", ("onsen", "snow")),
    SceneCard("island-art", "Art on a quiet island", ("art", "coast")),
    SceneCard("satoyama-village", "Satoyama farm village", ("nature", "culture")),
    SceneCard("castle-town", "Castle town and old streets", ("culture",)),
    SceneCard("fishing-village", "Fishing village by the sea", ("coast", "food")),
    SceneCard("mountain-views", "Big mountain views", ("nature", "hiking")),
    SceneCard("market-food", "Local market food", ("food",)),
    SceneCard("temple-stay", "Night at a mountain temple", ("culture", "nature")),
    SceneCard("powder-snow", "Powder snow and winter sports", ("snow",)),
    SceneCard("subtropical-beach", "Subtropical beaches", ("coast", "nature")),
)
SCENE_CARD_BY_SLUG = {card.slug: card for card in SCENE_CARDS}


class PastTripPreferences(BaseModel):
    """Structured output of the past-trip extraction prompt."""

    liked: list[Interest] = Field(default_factory=list, max_length=5)
    avoid: list[Avoid] = Field(default_factory=list, max_length=5)


_LIKE_WORDS: dict[str, tuple[str, ...]] = {
    "food": ("food", "market", "eat", "sushi", "ramen", "izakaya", "seafood", "nishiki", "sake"),
    "onsen": ("onsen", "hot spring", "bath", "ryokan"),
    "snow": ("snow", "ski", "winter"),
    "nature": ("nature", "mountain", "forest", "lake", "scenery", "countryside", "garden"),
    "hiking": ("hike", "hiking", "trek", "trail"),
    "culture": ("temple", "shrine", "castle", "history", "museum", "tea ceremony", "samurai"),
    "city": ("shopping", "neon", "skyline"),
    "coast": ("beach", "coast", "island", "ocean", "fishing"),
    "art": ("art", "gallery", "architecture", "design"),
    "nightlife": ("bar", "nightlife", "club", "karaoke"),
}
_AVOID_WORDS: dict[Avoid, tuple[str, ...]] = {
    Avoid.CROWDS: ("crowd", "busy", "packed", "queue", "tourists"),
    Avoid.LONG_TRANSFERS: ("long train", "long journey", "travel time", "transfers", "commut"),
    Avoid.HOTEL_CHANGES: ("packing", "changing hotels", "hotel changes", "moving hotels"),
    Avoid.CITIES: ("big cit", "the city", "cities", "urban"),
    Avoid.EARLY_STARTS: ("early start", "early morning", "alarm"),
}


def _mentions(text: str, words: Iterable[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}", text) for word in words)


def keyword_past_trip(best: str | None, tired: str | None) -> PastTripPreferences:
    """Deterministic extraction. Likes come from the best moment, avoids from what tired you.

    A traveller often writes both in one answer ("Loved Nishiki Market food
    walks, tired of crowds"), so avoid words are read from both answers.
    """
    best_text = (best or "").lower()
    tired_text = (tired or "").lower()
    liked = [Interest(t) for t, words in _LIKE_WORDS.items() if _mentions(best_text, words)]
    avoid = [
        kind
        for kind, words in _AVOID_WORDS.items()
        if _mentions(f"{best_text} {tired_text}", words)
    ]
    return PastTripPreferences(liked=liked[:5], avoid=avoid[:5])


def interests_from(
    explicit: Iterable[str], scene_cards: Iterable[str], liked: Iterable[str]
) -> tuple[str, ...]:
    """Explicit chips win. Otherwise the most-picked themes from cards and past trips."""
    chosen = [i for i in dict.fromkeys(explicit) if i in Interest.__members__.values()]
    if chosen:
        return tuple(chosen[:MAX_INTERESTS])
    counts: Counter[str] = Counter()
    order: dict[str, int] = {}
    for slug in scene_cards:
        card = SCENE_CARD_BY_SLUG.get(slug)
        for theme in card.themes if card else ():
            counts[theme] += 1
            order.setdefault(theme, len(order))
    for theme in liked:
        counts[theme] += 2  # said in their own words: weigh it above a picture
        order.setdefault(theme, len(order))
    ranked = sorted(counts, key=lambda t: (-counts[t], order[t]))
    return tuple(ranked[:MAX_INTERESTS])


@dataclass
class Preferences:
    theme_boost: dict[str, float] = field(default_factory=dict)
    liked_areas: set[str] = field(default_factory=set)
    excluded: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    quiet: int = 0
    unexpected: int = 0
    fewer_stops: bool = False
    avoid_cities: bool = False
    #: multiplies the travel budget; below 1 means "less moving, please"
    travel_factor: float = 1.0


def preferences_from(conditions: Conditions, places_by_slug: dict[str, object]) -> Preferences:
    prefs = Preferences()
    for avoid in conditions.avoid:
        if avoid is Avoid.CROWDS:
            prefs.quiet += 1
        elif avoid is Avoid.LONG_TRANSFERS:
            prefs.travel_factor = 0.85
        elif avoid is Avoid.HOTEL_CHANGES:
            prefs.fewer_stops = True
        elif avoid is Avoid.CITIES:
            prefs.avoid_cities = True
    pinned = set(conditions.must_include)
    for reaction in conditions.reactions:
        stops = [s for s in reaction.stops if s in places_by_slug]
        if reaction.kind is ReactionKind.MORE_LIKE_THIS:
            for slug in stops:
                place = places_by_slug[slug]
                for theme in getattr(place, "themes", ()):
                    prefs.theme_boost[theme] = prefs.theme_boost.get(theme, 0.0) + 1.0
                prefs.liked_areas.add(getattr(place, "area", ""))
        elif reaction.kind is ReactionKind.QUIETER:
            prefs.quiet += 1
            prefs.seen.update(stops)
        elif reaction.kind is ReactionKind.MORE_UNEXPECTED:
            prefs.unexpected += 1
            prefs.seen.update(stops)
        elif reaction.kind is ReactionKind.NOT_FOR_ME:
            prefs.excluded.update(s for s in stops if s not in pinned)
    return prefs
