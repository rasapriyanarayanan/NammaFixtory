"""Small shared helpers."""
import math
from datetime import datetime, timedelta

ISO = "%Y-%m-%dT%H:%M:%S"


def now(offset_days: float = 0.0) -> datetime:
    return datetime.now().replace(microsecond=0) + timedelta(days=offset_days)


def iso(dt: datetime) -> str:
    return dt.strftime(ISO)


def parse(ts: str) -> datetime:
    return datetime.strptime(ts[:19], ISO)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distance in metres between two GPS points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Issue categories -> infrastructure "family". An asset is matched within a family.
FAMILY = {
    "pothole": "road",
    "road_crack": "road",
    "road_damage": "road",
    "blocked_drain": "drainage",
    "waterlogging": "drainage",
    "water_leakage": "drainage",
    "garbage": "sanitation",
    "streetlight": "public",
    "other": "public",
}

CATEGORY_LABEL = {
    "pothole": "Pothole",
    "road_crack": "Road crack",
    "road_damage": "Road surface damage",
    "blocked_drain": "Blocked drain",
    "waterlogging": "Waterlogging",
    "water_leakage": "Water leakage",
    "garbage": "Garbage accumulation",
    "streetlight": "Damaged streetlight / public facility",
    "other": "Other",
}

DEPARTMENT = {
    "road": "Roads & Bridges",
    "drainage": "Storm Water Drain / Water Management",
    "sanitation": "Solid Waste Management",
    "public": "Public Works",
}
