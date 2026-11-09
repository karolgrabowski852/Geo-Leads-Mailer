import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx
from django.conf import settings
from apps.web.email_validation import extract_valid_emails
from apps.web.overpass_cache import OverpassAPIError, OverpassCache

logger = logging.getLogger(__name__)

MAX_POLYGON_POINTS = 200
MAX_RESULTS = 1000
MAX_CUSTOM_CATEGORY_LENGTH = 100


@dataclass(frozen=True)
class SearchCategory:
    key: str
    label: str
    tag_value: str | None = None
    aliases: tuple[str, ...] = ()
    text_query: str | None = None
    osm_key: str = "office"


CATEGORIES = (
    SearchCategory(
        "it",
        "Firmy IT i programistyczne",
        "it",
        (
            "software house",
            "software houses",
            "programowanie",
            "firmy informatyczne",
            "firmy it",
            "firmy programistyczne",
            "producenci oprogramowania",
        ),
    ),
    SearchCategory(
        "accountant",
        "Biura rachunkowe",
        "accountant",
        ("usługi księgowe", "biuro rachunkowe", "biura rachunkowe"),
    ),
    SearchCategory(
        "lawyer",
        "Kancelarie prawne",
        "lawyer",
        ("kancelaria prawna", "kancelarie adwokackie", "usługi prawne"),
    ),
    SearchCategory(
        "architect",
        "Biura architektoniczne",
        "architect",
        ("biuro architektoniczne", "projektowanie architektoniczne"),
    ),
    SearchCategory(
        "advertising_agency",
        "Agencje marketingowe i reklamowe",
        "advertising_agency",
        ("agencja reklamowa", "agencje reklamowe", "agencje marketingowe"),
    ),
    SearchCategory(
        "estate_agent",
        "Biura nieruchomości",
        "estate_agent",
        ("biuro nieruchomości", "pośrednictwo w obrocie nieruchomościami"),
    ),
    SearchCategory(
        "insurance",
        "Firmy ubezpieczeniowe",
        "insurance",
        ("firma ubezpieczeniowa", "ubezpieczenia", "usługi ubezpieczeniowe"),
    ),
    SearchCategory(
        "tax_advisor",
        "Doradcy podatkowi",
        "tax_advisor",
        ("doradztwo podatkowe", "doradca podatkowy", "doradcy podatkowi"),
    ),
)
CUSTOM_TAG_CATEGORIES = (
    SearchCategory(
        "printing",
        "Drukarnie",
        "printing",
        ("drukarnia", "drukarnie"),
        osm_key="shop",
    ),
)

CATEGORY_CHOICES = tuple((category.key, category.label) for category in CATEGORIES) + (
    ("custom", "Własna kategoria"),
)
CATEGORIES_BY_KEY = {category.key: category for category in CATEGORIES}
CATEGORY_ALIASES = {
    " ".join(alias.casefold().split()): category
    for category in CATEGORIES + CUSTOM_TAG_CATEGORIES
    for alias in category.aliases
}


@dataclass(frozen=True)
class Point:
    lat: float
    lng: float


@dataclass(frozen=True)
class Rect:
    low: Point
    high: Point


class _RetryableOverpassAPIError(OverpassAPIError):
    pass


def _normalise_phrase(value: str) -> str:
    return " ".join(value.split())


def resolve_category(selected: str, custom_phrase: str = "") -> SearchCategory:
    if selected != "custom":
        try:
            return CATEGORIES_BY_KEY[selected]
        except KeyError as exc:
            raise ValueError("Choose a category from the list.") from exc

    phrase = _normalise_phrase(custom_phrase)
    if not phrase:
        raise ValueError("Enter a custom category.")
    if len(phrase) > MAX_CUSTOM_CATEGORY_LENGTH:
        raise ValueError(
            f"A custom category can contain at most "
            f"{MAX_CUSTOM_CATEGORY_LENGTH} characters."
        )
    if not any(character.isalnum() for character in phrase):
        raise ValueError("A category must contain letters or numbers.")
    if any(ord(character) < 32 for character in phrase):
        raise ValueError("The category contains invalid characters.")

    alias = CATEGORY_ALIASES.get(phrase.casefold())
    if alias:
        return alias
    return SearchCategory(
        "custom",
        f"Własna kategoria: {phrase}",
        text_query=phrase,
    )


def _normalise_website(value: str) -> str | None:
    website = value.strip()
    if not website or len(website) > 200:
        return None
    if not re.match(r"^https?://", website, re.IGNORECASE):
        website = f"https://{website}"
    try:
        parsed = urlsplit(website)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None
    path = parsed.path.rstrip("/") if parsed.path in {"", "/"} else parsed.path
    normalized = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, path, parsed.query, "")
    )
    return normalized if len(normalized) <= 200 else None


class PolygonQuery:
    def __init__(
        self,
        polygon_coords: list[dict],
    ):
        self.category: SearchCategory | None = None
        if not isinstance(polygon_coords, list):
            raise ValueError("The polygon must be a list of points.")
        if len(polygon_coords) < 3:
            raise ValueError("The polygon must contain at least 3 points.")
        if len(polygon_coords) > MAX_POLYGON_POINTS:
            raise ValueError("The polygon contains too many points.")

        self.polygon = []
        for raw_point in polygon_coords:
            try:
                lat = float(raw_point["lat"])
                lng = float(raw_point["lng"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid polygon point format.") from exc
            if (
                not math.isfinite(lat)
                or not math.isfinite(lng)
                or not -90 <= lat <= 90
                or not -180 <= lng <= 180
            ):
                raise ValueError("Polygon coordinates are out of range.")
            self.polygon.append(Point(lat=lat, lng=lng))

    def set_category(self, category: SearchCategory) -> "PolygonQuery":
        self.category = category
        return self

    def set_query(self, query: str) -> "PolygonQuery":
        self.category = resolve_category("custom", query)
        return self

    @property
    def location_key(self) -> str:
        coordinates = [
            [round(point.lat, 6), round(point.lng, 6)] for point in self.polygon
        ]
        fingerprint = hashlib.sha256(
            json.dumps(coordinates, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return f"OSM-{fingerprint}"

    def get_bounding_box(self) -> Rect:
        return Rect(
            low=Point(
                lat=min(point.lat for point in self.polygon),
                lng=min(point.lng for point in self.polygon),
            ),
            high=Point(
                lat=max(point.lat for point in self.polygon),
                lng=max(point.lng for point in self.polygon),
            ),
        )

    @staticmethod
    def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
        cross = (point.lat - start.lat) * (end.lng - start.lng) - (
            point.lng - start.lng
        ) * (end.lat - start.lat)
        if abs(cross) > 1e-10:
            return False
        return (
            min(start.lat, end.lat) - 1e-10
            <= point.lat
            <= max(start.lat, end.lat) + 1e-10
            and min(start.lng, end.lng) - 1e-10
            <= point.lng
            <= max(start.lng, end.lng) + 1e-10
        )

    @classmethod
    def _point_in_ring(cls, point: Point, ring: list[Point]) -> bool:
        if len(ring) < 3:
            return False
        inside = False
        previous = ring[-1]
        for current in ring:
            if cls._point_on_segment(point, previous, current):
                return True
            if (current.lat > point.lat) != (previous.lat > point.lat):
                crossing_lng = (
                    (previous.lng - current.lng)
                    * (point.lat - current.lat)
                    / (previous.lat - current.lat)
                    + current.lng
                )
                if point.lng < crossing_lng:
                    inside = not inside
            previous = current
        return inside

    def is_point_in_polygon(self, lat: float, lng: float) -> bool:
        return self._point_in_ring(Point(lat=lat, lng=lng), self.polygon)

    @staticmethod
    def _intersection(
        first_start: Point,
        first_end: Point,
        second_start: Point,
        second_end: Point,
    ) -> Point | None:
        x1, y1 = first_start.lng, first_start.lat
        x2, y2 = first_end.lng, first_end.lat
        x3, y3 = second_start.lng, second_start.lat
        x4, y4 = second_end.lng, second_end.lat
        denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denominator) < 1e-12:
            return None
        determinant1 = x1 * y2 - y1 * x2
        determinant2 = x3 * y4 - y3 * x4
        intersection = Point(
            lat=(
                determinant1 * (y3 - y4) - (y1 - y2) * determinant2
            )
            / denominator,
            lng=(
                determinant1 * (x3 - x4) - (x1 - x2) * determinant2
            )
            / denominator,
        )
        if (
            min(x1, x2) - 1e-10 <= intersection.lng <= max(x1, x2) + 1e-10
            and min(y1, y2) - 1e-10 <= intersection.lat <= max(y1, y2) + 1e-10
            and min(x3, x4) - 1e-10 <= intersection.lng <= max(x3, x4) + 1e-10
            and min(y3, y4) - 1e-10 <= intersection.lat <= max(y3, y4) + 1e-10
        ):
            return intersection
        return None

    @staticmethod
    def _geometry_points(raw_points: object) -> list[Point]:
        if not isinstance(raw_points, list):
            return []
        points = []
        for point in raw_points:
            if not isinstance(point, dict):
                continue
            try:
                lat = float(point["lat"])
                lng = float(point["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(lat) and math.isfinite(lng):
                points.append(Point(lat=lat, lng=lng))
        return points

    def _geometry_groups(self, element: dict) -> list[tuple[str, list[Point]]]:
        element_type = element.get("type")
        if element_type == "node":
            points = self._geometry_points(
                [{"lat": element.get("lat"), "lon": element.get("lon")}]
            )
            return [("outer", points)] if points else []
        if element_type == "way":
            points = self._geometry_points(element.get("geometry"))
            return [("outer", points)] if points else []
        if element_type == "relation":
            groups = []
            for member in element.get("members", []):
                if not isinstance(member, dict):
                    continue
                points = self._geometry_points(member.get("geometry"))
                if points:
                    groups.append((member.get("role", ""), points))
                elif member.get("type") == "node":
                    points = self._geometry_points(
                        [{"lat": member.get("lat"), "lon": member.get("lon")}]
                    )
                    if points:
                        groups.append((member.get("role", ""), points))
            return groups
        return []

    def _representative_point(self, element: dict) -> Point | None:
        groups = self._geometry_groups(element)
        if not groups:
            return None

        outer_rings = [
            points
            for role, points in groups
            if role != "inner" and len(points) >= 4 and points[0] == points[-1]
        ]
        inner_rings = [
            points
            for role, points in groups
            if role == "inner" and len(points) >= 4 and points[0] == points[-1]
        ]

        def belongs_to_object(point: Point) -> bool:
            return any(
                self._point_in_ring(point, ring) for ring in outer_rings
            ) and not any(self._point_in_ring(point, ring) for ring in inner_rings)

        for role, points in groups:
            if role == "inner":
                continue
            for point in points:
                if self._point_in_ring(point, self.polygon) and (
                    not outer_rings or belongs_to_object(point)
                ):
                    return point

        for role, points in groups:
            if role == "inner":
                continue
            for start, end in zip(points, points[1:]):
                for polygon_start, polygon_end in zip(
                    self.polygon, self.polygon[1:] + self.polygon[:1]
                ):
                    point = self._intersection(
                        start, end, polygon_start, polygon_end
                    )
                    if point is not None and (
                        not outer_rings or belongs_to_object(point)
                    ):
                        return point

        for ring in outer_rings:
            for point in self.polygon:
                if self._point_in_ring(point, ring) and not any(
                    self._point_in_ring(point, inner_ring)
                    for inner_ring in inner_rings
                ):
                    return point
        return None

    @staticmethod
    def _format_address(tags: dict) -> str:
        full_address = tags.get("addr:full")
        if full_address:
            return str(full_address)
        street = tags.get("addr:street", "")
        house_number = tags.get("addr:housenumber", "")
        street_address = " ".join(
            part for part in (str(street), str(house_number)) if part
        )
        parts = [
            street_address,
            str(tags.get("addr:postcode", "")),
            str(tags.get("addr:city", "")),
        ]
        return ", ".join(part for part in parts if part)

    def build_query(self) -> str:
        if self.category is None:
            raise ValueError("Choose a search category.")
        bounds = self.get_bounding_box()
        bbox = (
            f"({bounds.low.lat:.6f},{bounds.low.lng:.6f},"
            f"{bounds.high.lat:.6f},{bounds.high.lng:.6f})"
        )
        if self.category.tag_value:
            selector = (
                f'nwr["{self.category.osm_key}"='
                f'"{self.category.tag_value}"]{bbox};'
            )
        else:
            phrase = re.escape(self.category.text_query or "")
            escaped_phrase = json.dumps(phrase, ensure_ascii=False)
            selector = (
                f'nwr["name"~{escaped_phrase},i]{bbox};'
                f'nwr["name:pl"~{escaped_phrase},i]{bbox};'
            )
        return (
            "[out:json][timeout:25];\n"
            f"(\n{selector}\n);\n"
            f"out body geom {MAX_RESULTS};"
        )

    def _fetch_elements(self, query: str) -> list[dict]:
        endpoints = [settings.OVERPASS_API_URL]
        for endpoint in settings.OVERPASS_API_FALLBACK_URLS:
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)

        return OverpassCache.get_or_fetch(
            endpoints,
            query,
            lambda: self._request_from_endpoints(endpoints, query),
        )

    def _request_from_endpoints(
        self, endpoints: list[str], query: str
    ) -> list[dict]:
        for index, endpoint in enumerate(endpoints):
            try:
                return self._request_elements(endpoint, query, max_attempts=1)
            except _RetryableOverpassAPIError as exc:
                if index == len(endpoints) - 1:
                    raise
                logger.warning(
                    "Overpass endpoint %s failed: %s; retrying on %s",
                    endpoint,
                    exc,
                    endpoints[index + 1],
                )
        raise OverpassAPIError("No Overpass endpoint is configured.")

    @staticmethod
    def _request_elements(
        endpoint: str,
        query: str,
        max_attempts: int = 3,
    ) -> list[dict]:
        user_agent = settings.OVERPASS_USER_AGENT
        headers = {
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        for attempt in range(max_attempts):
            try:
                response = httpx.post(
                    endpoint,
                    data={"data": query},
                    headers=headers,
                    timeout=25,
                )
            except httpx.RequestError as exc:
                if attempt < max_attempts - 1:
                    delay = 2**attempt
                    logger.warning(
                        "Overpass request failed; retry %s/%s in %s seconds: %s",
                        attempt + 1,
                        max_attempts - 1,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    continue
                raise _RetryableOverpassAPIError(
                    "Could not connect to OpenStreetMap. Please try again later."
                ) from exc

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < max_attempts - 1:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = min(max(float(retry_after), 0), 5)
                    except ValueError:
                        delay = 2**attempt
                    logger.warning(
                        "Overpass API returned HTTP %s; retry %s/%s in %s seconds",
                        response.status_code,
                        attempt + 1,
                        max_attempts - 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
            if response.status_code >= 400:
                message = (
                    "OpenStreetMap returned HTTP "
                    f"{response.status_code}. Please try again later."
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise _RetryableOverpassAPIError(message)
                raise OverpassAPIError(message)
            try:
                payload = response.json()
            except ValueError as exc:
                raise OverpassAPIError(
                    "OpenStreetMap returned an invalid response."
                ) from exc
            if not isinstance(payload, dict) or not isinstance(
                payload.get("elements"), list
            ):
                raise OverpassAPIError(
                    "OpenStreetMap returned an invalid response."
                )
            if payload.get("remark"):
                logger.warning("Overpass API returned a remark: %s", payload["remark"])
                raise OverpassAPIError(
                    "The OpenStreetMap search exceeded the available limits. "
                    "Draw a smaller area and try again."
                )
            return payload["elements"][:MAX_RESULTS]

        raise OverpassAPIError(
            "OpenStreetMap is temporarily overloaded. Please try again later."
        )

    def _normalise_element(self, element: dict) -> dict | None:
        osm_type = element.get("type")
        osm_id = element.get("id")
        if osm_type not in {"node", "way", "relation"} or not isinstance(
            osm_id, int
        ):
            return None
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}

        location = self._representative_point(element)
        if location is None:
            return None

        name = str(
            tags.get("name")
            or tags.get("brand")
            or tags.get("operator")
            or f"Firma bez nazwy (OSM {osm_type}/{osm_id})"
        )
        name = name[:255]
        website = _normalise_website(
            str(tags.get("website") or tags.get("contact:website") or "")
        )
        email_values = [
            str(value)
            for value in (tags.get("email"), tags.get("contact:email"))
            if value
        ]
        email = ", ".join(extract_valid_emails(" ".join(email_values)))
        phone = str(tags.get("phone") or tags.get("contact:phone") or "")
        category = (
            f"{self.category.osm_key}={self.category.tag_value}"
            if self.category and self.category.tag_value
            else (self.category.label if self.category else "")
        )
        address = self._format_address(tags)
        return {
            "osm_id": osm_id,
            "osm_type": osm_type,
            "source": "osm",
            "name": str(name),
            "displayName": {"text": str(name)},
            "category": category,
            "website": website,
            "websiteUri": website,
            "osm_email": email,
            "email": email,
            "phone": phone,
            "nationalPhoneNumber": phone,
            "address": address,
            "formattedAddress": address,
            "latitude": location.lat,
            "longitude": location.lng,
            "location": {
                "latitude": location.lat,
                "longitude": location.lng,
            },
            "osm_tags": tags,
        }

    def search(self) -> dict:
        if self.category is None:
            raise ValueError("Choose a search category.")
        query = self.build_query()
        elements = self._fetch_elements(query)
        unique_elements = {}
        for element in elements:
            if not isinstance(element, dict):
                continue
            normalised = self._normalise_element(element)
            if normalised is None:
                continue
            key = f"{normalised['osm_type']}/{normalised['osm_id']}"
            unique_elements[key] = normalised

        logger.info(
            "Overpass returned %s companies inside the selected polygon",
            len(unique_elements),
        )
        results = {
            f"polygon_search_{self.category.label}": unique_elements,
            "search_mode": "text" if self.category.text_query else "tag",
        }
        if self.category.text_query:
            results["search_message"] = (
                "No exact OSM tag was found for this phrase. "
                "A text search by object name was performed."
            )
        return results
