from abc import ABC, abstractmethod
from typing import Self

import httpx
from pydantic import BaseModel

from apps.config import config, logger


class Point(BaseModel):
    lat: float
    lng: float


class Rect(BaseModel):
    low: Point
    high: Point


class Query(ABC):
    def __init__(self, language="pl", country="PL"):
        self.language = language
        self.country = country
        self.query = ""

    @abstractmethod
    def search(self) -> dict:
        pass

    def set_query(self, query: str) -> Self:
        self.query = query
        return self


class PolygonQuery(Query):
    def __init__(
        self,
        polygon_coords: list[dict],
        language: str = "pl",
        country: str = "PL",
    ):
        super().__init__(language=language, country=country)
        self.polygon = [Point(**p) for p in polygon_coords]

    def get_bounding_box(self) -> Rect:
        """Tworzy prostokąt ograniczający (Bounding Box) dla poligonu."""
        lats = [p.lat for p in self.polygon]
        lngs = [p.lng for p in self.polygon]
        return Rect(
            low=Point(lat=min(lats), lng=min(lngs)),
            high=Point(lat=max(lats), lng=max(lngs)),
        )

    def is_point_in_polygon(self, lat: float, lng: float) -> bool:
        """Ray-Casting: sprawdza, czy punkt leży wewnątrz obszaru."""
        n = len(self.polygon)
        inside = False
        p1 = self.polygon[0]
        for i in range(1, n + 1):
            p2 = self.polygon[i % n]
            if min(p1.lng, p2.lng) < lng <= max(p1.lng, p2.lng):
                if lat <= max(p1.lat, p2.lat):
                    if p1.lng != p2.lng:
                        xinters = (lng - p1.lng) * (p2.lat - p1.lat) / (
                            p2.lng - p1.lng
                        ) + p1.lat
                    if p1.lat == p2.lat or lat <= xinters:
                        inside = not inside
            p1 = p2
        return inside

    def search(self) -> dict:
        api_key = (config.google_location_api_key or "").strip()
        if not api_key:
            raise ValueError(
                "Brak klucza Google Places API. Ustaw GOOGLE_LOCATION_API_KEY."
            )

        unique_places = {}
        bounds = self.get_bounding_box()

        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.websiteUri,places.nationalPhoneNumber,"
                "places.location,nextPageToken"
            ),
        }

        next_page_token = None
        for _ in range(5):  # Max 5 stron wyników (ok. 100 miejsc)
            data = {
                "textQuery": self.query,
                "languageCode": self.language,
                "regionCode": self.country,
                "pageSize": 20,
                "locationRestriction": {
                    "rectangle": {
                        "low": {
                            "latitude": bounds.low.lat,
                            "longitude": bounds.low.lng,
                        },
                        "high": {
                            "latitude": bounds.high.lat,
                            "longitude": bounds.high.lng,
                        },
                    }
                },
            }
            if next_page_token:
                data["pageToken"] = next_page_token

            try:
                response = httpx.post(
                    url,
                    json=data,
                    headers=headers,
                    timeout=30,
                )
            except httpx.RequestError as exc:
                raise RuntimeError(
                    "Nie udalo sie polaczyc z Google Places API."
                ) from exc

            try:
                res_data = response.json()
            except ValueError:
                res_data = {}

            if response.status_code >= 400:
                error_payload = {}
                if isinstance(res_data, dict):
                    error_payload = res_data.get("error", {})

                api_message = error_payload.get("message") or "Brak szczegolow bledu."

                if response.status_code in (401, 403):
                    raise ValueError(
                        "Brak dostepu do Google Places API. "
                        "Sprawdz klucz API i uprawnienia projektu. "
                        f"Szczegoly: {api_message}"
                    )

                raise RuntimeError(
                    "Google Places API zwrocilo blad "
                    f"{response.status_code}. Szczegoly: {api_message}"
                )

            if "places" in res_data:
                for place in res_data["places"]:
                    loc = place.get("location", {})
                    lat, lng = loc.get("latitude"), loc.get("longitude")

                    if (
                        lat is not None
                        and lng is not None
                        and self.is_point_in_polygon(lat, lng)
                    ):
                        place_id = place.get("id")
                        place_key = place_id or place.get("displayName", {}).get(
                            "text",
                            "Unknown",
                        )
                        if place_key not in unique_places:
                            unique_places[place_key] = place

            next_page_token = res_data.get("nextPageToken")
            if not next_page_token:
                break

        logger.info(f"Zaleziono {len(unique_places)} firm w zdefiniowanym poligonie.")
        return {f"polygon_search_{self.query}": unique_places}
