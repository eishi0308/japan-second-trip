"""Seed fragile-link records for ~30 fragile destinations. DEMO DATA.

A fragile link is a fact that can break a stay: the last bus of the day, a
ryokan shuttle, a seasonal closure, a weekly closure, a booking rule, a
weather cancellation.

These are hand-authored demo records, not facts checked against an operator.
Times and rules are plausible illustrations of the *kind* of constraint each
place has. Each record is ``is_demo=True`` and gets a DEMO source row, so the
UI can show a source and a date and still label it DEMO.

The statuses are deliberately mixed so every state in PRODUCT_AMENDMENTS.md §7
has real data behind it:

* ``verified_days_ago`` set and within the TTL: verified, with a date.
* ``verified_days_ago`` beyond ``ttl_days``: stale.
* ``verified_days_ago`` is None: unverified ("No verified info yet").
* ``status="conflicting"`` with ``conflicting_values``: "Being checked". No
  single value is asserted. The Ginzan Onsen record matches the seeded
  conflict in ``seed/evidence.py`` (KNOWN_CONFLICTS).

Months are 1-12. Weekdays are 0 = Monday.
"""

from __future__ import annotations

from typing import Any

_DEFAULTS: dict[str, Any] = {
    "last_departure_local": None,
    "closed_months": [],
    "closed_weekdays": [],
    "lead_time_days": None,
    "frequency_per_day": None,
    "status": "verified",
    "conflicting_values": [],
    "verified_days_ago": 60,
    "ttl_days": 180,
}

_FRAGILE: list[dict[str, Any]] = [
    # ---- Tohoku ------------------------------------------------------------
    {
        "destination_slug": "ginzan-onsen",
        "kind": "last_connection",
        "severity": "critical",
        "title": "Last bus from Oishida Station",
        "detail": "Buses from Oishida Station run only a few times a day. After the last one, "
        "the only way in is a taxi. Sources disagree on the winter last departure.",
        "status": "conflicting",
        "conflicting_values": ["17:00", "16:30", "18:10"],
        "frequency_per_day": 4,
        "verified_days_ago": 55,
    },
    {
        "destination_slug": "ginzan-onsen",
        "kind": "booking_difficulty",
        "severity": "warning",
        "title": "Ryokan book out months ahead in winter",
        "detail": "There are only a handful of ryokan in the village and the snow season is "
        "the busiest time. Day visitors cannot stay after dark without a booking.",
        "lead_time_days": 90,
        "verified_days_ago": 70,
    },
    {
        "destination_slug": "nyuto-onsen",
        "kind": "last_connection",
        "severity": "critical",
        "title": "Last bus from Tazawako Station",
        "detail": "The bus up to Nyuto runs several times a day. Miss the last one and the "
        "taxi ride up the mountain is long and expensive.",
        "last_departure_local": "16:45",
        "frequency_per_day": 7,
        "verified_days_ago": 40,
    },
    {
        "destination_slug": "nyuto-onsen",
        "kind": "ryokan_shuttle",
        "severity": "warning",
        "title": "Ryokan pick-up must be booked",
        "detail": "Some ryokan meet the bus with their own shuttle, but only for guests who "
        "asked for it when booking.",
        "verified_days_ago": None,
    },
    {
        "destination_slug": "sukayu-onsen",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Blizzards close the road and the Hakkoda ropeway",
        "detail": "Heavy snow can stop buses and the ropeway for a day. Keep the next "
        "day's plans flexible.",
        "closed_months": [],
        "verified_days_ago": 60,
    },
    {
        "destination_slug": "sukayu-onsen",
        "kind": "last_connection",
        "severity": "critical",
        "title": "Last bus back to Aomori",
        "detail": "Winter buses to and from Aomori are few, and the last one leaves in the "
        "afternoon.",
        "verified_days_ago": None,
    },
    {
        "destination_slug": "oirase",
        "kind": "low_frequency",
        "severity": "warning",
        "title": "Few buses outside the autumn season",
        "detail": "The gorge bus runs often in autumn and much less in winter, when some "
        "services stop.",
        "frequency_per_day": 4,
        "verified_days_ago": 210,
    },
    {
        "destination_slug": "ouchi-juku",
        "kind": "low_frequency",
        "severity": "warning",
        "title": "Shuttle from Yunokami-Onsen Station",
        "detail": "The station shuttle to the village is seasonal. Outside its season a taxi "
        "is the only option.",
        "verified_days_ago": 300,
    },
    {
        "destination_slug": "dewa-sanzan",
        "kind": "seasonal_closure",
        "severity": "critical",
        "title": "Gassan and Yudono-san close in winter",
        "detail": "Only Haguro-san is open all year. The other two mountains close in winter.",
        "closed_months": [11, 12, 1, 2, 3, 4],
        "verified_days_ago": 90,
    },
    # ---- Kanto ---------------------------------------------------------------
    {
        "destination_slug": "okunikko-yumoto",
        "kind": "low_frequency",
        "severity": "warning",
        "title": "Hourly bus from Nikko",
        "detail": "The bus up from Nikko is roughly hourly and takes over an hour.",
        "frequency_per_day": 12,
        "verified_days_ago": 100,
    },
    # ---- Chubu and the Alps --------------------------------------------------
    {
        "destination_slug": "kamikochi",
        "kind": "seasonal_closure",
        "severity": "critical",
        "title": "Closed mid-November to mid-April",
        "detail": "The road into Kamikochi closes for winter and the hotels close with it.",
        "closed_months": [12, 1, 2, 3],
        "verified_days_ago": 50,
    },
    {
        "destination_slug": "kamikochi",
        "kind": "last_connection",
        "severity": "warning",
        "title": "Last bus out to Shin-Shimashima",
        "detail": "Day visitors must leave on the last bus out of the valley.",
        "last_departure_local": "17:00",
        "verified_days_ago": 200,
    },
    {
        "destination_slug": "shirahone-onsen",
        "kind": "seasonal_closure",
        "severity": "warning",
        "title": "Winter bus service",
        "detail": "Winter road conditions affect the bus into Shirahone. The winter service "
        "pattern has not been checked.",
        "verified_days_ago": None,
    },
    {
        "destination_slug": "nozawa-onsen",
        "kind": "booking_difficulty",
        "severity": "warning",
        "title": "Fire festival night books out early",
        "detail": "Rooms for the mid-January fire festival are booked very far in advance.",
        "lead_time_days": 300,
        "verified_days_ago": 80,
    },
    {
        "destination_slug": "jigokudani",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Icy trail to the monkey park",
        "detail": "The forest trail to the park is icy in winter. Good shoes or grips help.",
        "verified_days_ago": 45,
    },
    {
        "destination_slug": "okuhida-onsen",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Shinhotaka ropeway stops in strong wind",
        "detail": "The ropeway can suspend service in bad weather.",
        "verified_days_ago": 130,
    },
    {
        "destination_slug": "shirakawa-go",
        "kind": "booking_difficulty",
        "severity": "critical",
        "title": "Winter light-up needs a reserved bus or tour",
        "detail": "On light-up evenings the village limits visitors. Entry needs a reserved "
        "bus seat, a tour or a room in the village.",
        "lead_time_days": 60,
        "verified_days_ago": 40,
    },
    {
        "destination_slug": "shirakawa-go",
        "kind": "last_connection",
        "severity": "warning",
        "title": "Last highway bus to Kanazawa",
        "detail": "The last bus back to Kanazawa leaves in the late afternoon.",
        "last_departure_local": "17:40",
        "verified_days_ago": 40,
    },
    {
        "destination_slug": "echigo-yuzawa",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Heavy snow delays local lines",
        "detail": "The shinkansen keeps running, but local lines beyond Yuzawa can be "
        "delayed by snow.",
        "verified_days_ago": 75,
    },
    # ---- Hokuriku --------------------------------------------------------------
    {
        "destination_slug": "tateyama",
        "kind": "seasonal_closure",
        "severity": "critical",
        "title": "Alpine Route closed December to mid-April",
        "detail": "The whole route closes for winter.",
        "closed_months": [12, 1, 2, 3],
        "verified_days_ago": 400,
        "ttl_days": 240,
    },
    {
        "destination_slug": "unazuki-onsen",
        "kind": "seasonal_closure",
        "severity": "critical",
        "title": "Kurobe Gorge Railway closed in winter",
        "detail": "The gorge trolley train does not run in winter. Unazuki itself stays open.",
        "closed_months": [12, 1, 2, 3],
        "verified_days_ago": 150,
    },
    {
        "destination_slug": "wajima",
        "kind": "access_disruption",
        "severity": "critical",
        "title": "Access after the 2024 Noto earthquake",
        "detail": "Roads, transport and opening hours on Noto have changed during recovery. "
        "The current situation has not been verified.",
        "verified_days_ago": None,
    },
    # ---- Kansai ----------------------------------------------------------------
    {
        "destination_slug": "ine",
        "kind": "low_frequency",
        "severity": "warning",
        "title": "Buses to Ine about hourly",
        "detail": "The bus from Amanohashidate is roughly hourly and stops in the evening.",
        "frequency_per_day": 10,
        "verified_days_ago": 90,
    },
    {
        "destination_slug": "koyasan",
        "kind": "booking_difficulty",
        "severity": "warning",
        "title": "Temple lodging must be booked; arrive before dinner",
        "detail": "Temple lodgings serve dinner early and expect guests to arrive in time.",
        "lead_time_days": 30,
        "verified_days_ago": 100,
    },
    {
        "destination_slug": "kumano-hongu",
        "kind": "last_connection",
        "severity": "critical",
        "title": "Last bus from Hongu",
        "detail": "Buses on the Kumano routes are sparse. Plan walking stages around the last bus.",
        "last_departure_local": "16:50",
        "frequency_per_day": 6,
        "verified_days_ago": 130,
    },
    # ---- Shikoku ---------------------------------------------------------------
    {
        "destination_slug": "naoshima",
        "kind": "weekly_closure",
        "severity": "critical",
        "title": "Most museums close on Mondays",
        "detail": "The main museums close on Mondays, and the next day when Monday is a holiday.",
        "closed_weekdays": [0],
        "verified_days_ago": 35,
    },
    {
        "destination_slug": "naoshima",
        "kind": "last_connection",
        "severity": "critical",
        "title": "Last ferry to Takamatsu",
        "detail": "The last ferry back to Takamatsu leaves in the early evening.",
        "last_departure_local": "18:05",
        "verified_days_ago": 35,
    },
    {
        "destination_slug": "teshima",
        "kind": "weekly_closure",
        "severity": "critical",
        "title": "Teshima Art Museum closes on Tuesdays",
        "detail": "The museum closes on Tuesdays, and on more days in winter.",
        "closed_weekdays": [1],
        "verified_days_ago": 120,
    },
    {
        "destination_slug": "iya-valley",
        "kind": "low_frequency",
        "severity": "critical",
        "title": "Few buses into the valley",
        "detail": "Buses into the inner valley run only a few times a day. A missed bus can "
        "cost half a day.",
        "frequency_per_day": 4,
        "verified_days_ago": 150,
    },
    # ---- Kyushu ----------------------------------------------------------------
    {
        "destination_slug": "kurokawa-onsen",
        "kind": "last_connection",
        "severity": "critical",
        "title": "Last bus from Yufuin",
        "detail": "The highway bus between Yufuin and Kurokawa runs only a few times a day.",
        "last_departure_local": "16:30",
        "verified_days_ago": 48,
    },
    {
        "destination_slug": "kurokawa-onsen",
        "kind": "booking_difficulty",
        "severity": "warning",
        "title": "Weekend ryokan book out",
        "detail": "The village has a limited number of ryokan, and weekends fill first.",
        "lead_time_days": 60,
        "verified_days_ago": 100,
    },
    {
        "destination_slug": "takachiho",
        "kind": "low_frequency",
        "severity": "critical",
        "title": "Only a few direct buses a day",
        "detail": "Direct buses from Kumamoto and Fukuoka are few. The night kagura ends "
        "after the last bus out.",
        "frequency_per_day": 2,
        "verified_days_ago": 90,
    },
    {
        "destination_slug": "takachiho",
        "kind": "booking_difficulty",
        "severity": "warning",
        "title": "Gorge rowing boats sell out",
        "detail": "Boat slots are limited and are reserved online.",
        "verified_days_ago": None,
    },
    {
        "destination_slug": "yakushima",
        "kind": "weather_cancellation",
        "severity": "critical",
        "title": "Fast ferries cancel in rough seas",
        "detail": "Jetfoil sailings are cancelled in high waves. Leave a buffer day before "
        "your flight home.",
        "verified_days_ago": 60,
    },
    {
        "destination_slug": "goto",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Ferries depend on the weather",
        "detail": "Sailings to the islands can be cancelled in winter storms and typhoons.",
        "verified_days_ago": 160,
    },
    # ---- Hokkaido --------------------------------------------------------------
    {
        "destination_slug": "shiretoko-utoro",
        "kind": "seasonal_closure",
        "severity": "critical",
        "title": "Shiretoko Pass road closed in winter",
        "detail": "The pass across the peninsula closes for winter, and the Five Lakes trail "
        "is limited outside summer.",
        "closed_months": [11, 12, 1, 2, 3, 4],
        "verified_days_ago": 200,
    },
    {
        "destination_slug": "abashiri",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Icebreaker cruises depend on the ice",
        "detail": "Drift-ice cruises run in winter and can be cancelled by wind or a lack of ice.",
        "lead_time_days": 14,
        "verified_days_ago": 90,
    },
    {
        "destination_slug": "rishiri",
        "kind": "weather_cancellation",
        "severity": "warning",
        "title": "Ferry from Wakkanai depends on the weather",
        "detail": "Sailings can be cancelled in rough seas, especially outside summer.",
        "verified_days_ago": None,
    },
]

FRAGILE_LINKS: list[dict[str, Any]] = [{**_DEFAULTS, **row} for row in _FRAGILE]
