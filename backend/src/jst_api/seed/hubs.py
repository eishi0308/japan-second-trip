"""Seed hubs and the intercity backbone. DEMO DATA.

Hub coordinates are real. Link times are hand-authored, typical door-to-door
times between city centres. They include airport access and check-in for
flights, and the transfer wait where ``transfers`` is above zero. They are
good enough to rank trips honestly. They are not a timetable, every row is
``is_demo=True``, and the UI labels anything built on them DEMO.

Each link is written once here; the loader stores both directions.
"""

from __future__ import annotations

# slug, name, name_ja, area, lat, lon, airports, international gateway
_HUBS: list[tuple[str, str, str, str, float, float, list[str], bool]] = [
    ("tokyo", "Tokyo", "東京", "kanto", 35.6812, 139.7671, ["HND", "NRT"], True),
    ("osaka", "Osaka", "大阪", "kansai", 34.7025, 135.4959, ["KIX", "ITM"], True),
    ("kyoto", "Kyoto", "京都", "kansai", 34.9858, 135.7588, [], False),
    ("nagoya", "Nagoya", "名古屋", "chubu", 35.1709, 136.8815, ["NGO"], True),
    ("sendai", "Sendai", "仙台", "tohoku", 38.2601, 140.8824, ["SDJ"], True),
    ("morioka", "Morioka", "盛岡", "tohoku", 39.7016, 141.1365, ["HNA"], False),
    ("aomori", "Aomori", "青森", "tohoku", 40.8270, 140.6935, ["AOJ"], False),
    ("akita", "Akita", "秋田", "tohoku", 39.7167, 140.1295, ["AXT"], False),
    ("yamagata", "Yamagata", "山形", "tohoku", 38.2490, 140.3279, ["GAJ"], False),
    ("niigata", "Niigata", "新潟", "chubu", 37.9121, 139.0610, ["KIJ"], False),
    ("nagano", "Nagano", "長野", "chubu", 36.6431, 138.1887, [], False),
    ("matsumoto", "Matsumoto", "松本", "chubu", 36.2309, 137.9643, ["MMJ"], False),
    ("toyama", "Toyama", "富山", "hokuriku", 36.7013, 137.2133, ["TOY"], False),
    ("kanazawa", "Kanazawa", "金沢", "hokuriku", 36.5780, 136.6480, ["KMQ"], False),
    ("hakodate", "Hakodate", "函館", "hokkaido", 41.7738, 140.7264, ["HKD"], False),
    ("sapporo", "Sapporo", "札幌", "hokkaido", 43.0687, 141.3508, ["CTS"], True),
    ("asahikawa", "Asahikawa", "旭川", "hokkaido", 43.7631, 142.3580, ["AKJ"], False),
    ("kushiro", "Kushiro", "釧路", "hokkaido", 42.9906, 144.3818, ["KUH"], False),
    ("okayama", "Okayama", "岡山", "chugoku", 34.6664, 133.9180, ["OKJ"], False),
    ("hiroshima", "Hiroshima", "広島", "chugoku", 34.3976, 132.4754, ["HIJ"], False),
    ("matsue", "Matsue", "松江", "chugoku", 35.4643, 133.0631, ["IZO"], False),
    ("takamatsu", "Takamatsu", "高松", "shikoku", 34.3505, 134.0469, ["TAK"], False),
    ("matsuyama", "Matsuyama", "松山", "shikoku", 33.8353, 132.7514, ["MYJ"], False),
    ("kochi", "Kochi", "高知", "shikoku", 33.5670, 133.5436, ["KCZ"], False),
    ("fukuoka", "Fukuoka", "福岡", "kyushu", 33.5898, 130.4207, ["FUK"], True),
    ("kumamoto", "Kumamoto", "熊本", "kyushu", 32.7898, 130.6886, ["KMJ"], False),
    ("oita", "Oita", "大分", "kyushu", 33.2336, 131.6066, ["OIT"], False),
    ("nagasaki", "Nagasaki", "長崎", "kyushu", 32.7522, 129.8697, ["NGS"], False),
    ("miyazaki", "Miyazaki", "宮崎", "kyushu", 31.9150, 131.4320, ["KMI"], False),
    ("kagoshima", "Kagoshima", "鹿児島", "kyushu", 31.5841, 130.5413, ["KOJ"], False),
    ("naha", "Naha", "那覇", "okinawa", 26.2124, 127.6792, ["OKA"], True),
]

HUBS: list[dict] = [
    {
        "slug": slug,
        "name": name,
        "name_ja": name_ja,
        "area": area,
        "lat": lat,
        "lon": lon,
        "airports": airports,
        "is_international_gateway": gateway,
    }
    for slug, name, name_ja, area, lat, lon, airports, gateway in _HUBS
]

# a, b, mode, minutes, transfers, note
_LINKS: list[tuple[str, str, str, int, int, str | None]] = [
    # ---- Tohoku and Hokkaido shinkansen corridor -------------------------
    ("tokyo", "sendai", "shinkansen", 95, 0, None),
    ("sendai", "morioka", "shinkansen", 40, 0, None),
    ("morioka", "aomori", "shinkansen", 60, 0, "Shin-Aomori is outside the city centre."),
    ("tokyo", "morioka", "shinkansen", 135, 0, None),
    ("tokyo", "aomori", "shinkansen", 190, 0, None),
    ("aomori", "hakodate", "shinkansen", 80, 1, "Change at Shin-Hakodate-Hokuto for the city."),
    ("tokyo", "hakodate", "shinkansen", 270, 1, None),
    ("hakodate", "sapporo", "limited_express", 230, 0, None),
    ("morioka", "akita", "shinkansen", 95, 0, None),
    ("tokyo", "akita", "shinkansen", 230, 0, None),
    ("tokyo", "yamagata", "shinkansen", 165, 0, None),
    ("sendai", "yamagata", "highway_bus", 80, 0, None),
    ("sapporo", "asahikawa", "limited_express", 85, 0, None),
    ("sapporo", "kushiro", "limited_express", 250, 0, None),
    # ---- Joetsu, Hokuriku and the Alps -----------------------------------
    ("tokyo", "niigata", "shinkansen", 120, 0, None),
    ("tokyo", "nagano", "shinkansen", 80, 0, None),
    ("nagano", "toyama", "shinkansen", 50, 0, None),
    ("toyama", "kanazawa", "shinkansen", 20, 0, None),
    ("tokyo", "toyama", "shinkansen", 130, 0, None),
    ("tokyo", "kanazawa", "shinkansen", 150, 0, None),
    ("nagano", "matsumoto", "limited_express", 50, 0, None),
    ("tokyo", "matsumoto", "limited_express", 160, 0, None),
    ("nagoya", "matsumoto", "limited_express", 125, 0, None),
    ("osaka", "kanazawa", "limited_express", 160, 1, "Change to the shinkansen at Tsuruga."),
    ("kyoto", "kanazawa", "limited_express", 140, 1, "Change to the shinkansen at Tsuruga."),
    ("nagoya", "kanazawa", "limited_express", 155, 1, "Change to the shinkansen at Tsuruga."),
    # ---- Tokaido and Sanyo -----------------------------------------------
    ("tokyo", "nagoya", "shinkansen", 100, 0, None),
    ("nagoya", "kyoto", "shinkansen", 35, 0, None),
    ("kyoto", "osaka", "shinkansen", 25, 0, None),
    ("tokyo", "kyoto", "shinkansen", 135, 0, None),
    ("tokyo", "osaka", "shinkansen", 150, 0, None),
    ("osaka", "okayama", "shinkansen", 45, 0, None),
    ("okayama", "hiroshima", "shinkansen", 35, 0, None),
    ("osaka", "hiroshima", "shinkansen", 85, 0, None),
    ("hiroshima", "fukuoka", "shinkansen", 65, 0, None),
    ("osaka", "fukuoka", "shinkansen", 150, 0, None),
    ("nagoya", "fukuoka", "shinkansen", 200, 0, None),
    ("tokyo", "okayama", "shinkansen", 200, 0, None),
    ("tokyo", "hiroshima", "shinkansen", 240, 0, None),
    # ---- San'in and Shikoku ----------------------------------------------
    ("okayama", "matsue", "limited_express", 160, 0, None),
    ("okayama", "takamatsu", "local_train", 55, 0, None),
    ("okayama", "matsuyama", "limited_express", 165, 0, None),
    ("okayama", "kochi", "limited_express", 155, 0, None),
    ("takamatsu", "matsuyama", "limited_express", 150, 0, None),
    ("takamatsu", "kochi", "limited_express", 130, 0, None),
    ("osaka", "takamatsu", "highway_bus", 190, 0, None),
    # ---- Kyushu ----------------------------------------------------------
    ("fukuoka", "kumamoto", "shinkansen", 35, 0, None),
    ("kumamoto", "kagoshima", "shinkansen", 45, 0, None),
    ("fukuoka", "kagoshima", "shinkansen", 80, 0, None),
    ("osaka", "kumamoto", "shinkansen", 185, 0, None),
    ("osaka", "kagoshima", "shinkansen", 240, 0, None),
    ("fukuoka", "nagasaki", "limited_express", 85, 1, "Change at Takeo-Onsen."),
    ("fukuoka", "oita", "limited_express", 125, 0, None),
    ("kagoshima", "miyazaki", "limited_express", 130, 0, None),
    ("oita", "miyazaki", "limited_express", 190, 0, None),
    # ---- Flights (door to door, including airport time) ------------------
    ("tokyo", "sapporo", "flight", 240, 0, None),
    ("tokyo", "hakodate", "flight", 230, 0, None),
    ("tokyo", "asahikawa", "flight", 260, 0, None),
    ("tokyo", "kushiro", "flight", 250, 0, None),
    ("tokyo", "fukuoka", "flight", 240, 0, None),
    ("tokyo", "kagoshima", "flight", 270, 0, None),
    ("tokyo", "nagasaki", "flight", 270, 0, None),
    ("tokyo", "miyazaki", "flight", 260, 0, None),
    ("tokyo", "oita", "flight", 250, 0, None),
    ("tokyo", "kochi", "flight", 240, 0, None),
    ("tokyo", "matsuyama", "flight", 240, 0, None),
    ("tokyo", "matsue", "flight", 250, 0, "Via Izumo airport."),
    ("tokyo", "naha", "flight", 300, 0, None),
    ("osaka", "sapporo", "flight", 270, 0, None),
    ("osaka", "naha", "flight", 270, 0, None),
    ("nagoya", "sapporo", "flight", 260, 0, None),
    ("nagoya", "naha", "flight", 280, 0, None),
    ("sendai", "sapporo", "flight", 230, 0, None),
    ("fukuoka", "naha", "flight", 230, 0, None),
]

HUB_LINKS: list[dict] = [
    {"a": a, "b": b, "mode": mode, "minutes": minutes, "transfers": transfers, "note": note}
    for a, b, mode, minutes, transfers, note in _LINKS
]
