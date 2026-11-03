import json
import re
from unittest.mock import Mock, patch

import httpx
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.web.web_search import (
    CATEGORY_CHOICES,
    OverpassAPIError,
    PolygonQuery,
    resolve_category,
)


@override_settings(
    OVERPASS_API_URL="https://overpass.example/interpreter",
    OVERPASS_API_FALLBACK_URL="",
    OVERPASS_API_FALLBACK_URLS=[],
    OVERPASS_USER_AGENT="GeoLeadsMailer-test/1.0",
)
class PolygonQueryTests(TestCase):
    polygon = [
        {"lat": 0, "lng": 0},
        {"lat": 0, "lng": 2},
        {"lat": 2, "lng": 2},
        {"lat": 2, "lng": 0},
    ]

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _searcher(self, category="it", phrase=""):
        return PolygonQuery(self.polygon).set_category(
            resolve_category(category, phrase)
        )

    def test_category_query_uses_documented_osm_tag_and_bbox(self):
        query = self._searcher().build_query()

        self.assertIn('nwr["office"="it"]', query)
        self.assertIn("(0.000000,0.000000,2.000000,2.000000)", query)
        self.assertIn("out body geom 500;", query)

    def test_custom_alias_maps_to_known_tag(self):
        category = resolve_category("custom", "  Software house ")
        self.assertEqual(category.tag_value, "it")
        self.assertEqual(category.label, "Firmy IT i programistyczne")

    def test_printing_alias_uses_documented_shop_tag(self):
        category = resolve_category("custom", "drukarnie")

        self.assertEqual((category.osm_key, category.tag_value), ("shop", "printing"))
        query = self._searcher("custom", "drukarnie").build_query()
        self.assertIn('nwr["shop"="printing"]', query)

    def test_unmatched_custom_phrase_uses_text_search(self):
        category = resolve_category("custom", "agencje SEO")

        self.assertIsNone(category.tag_value)
        self.assertEqual(category.text_query, "agencje SEO")

    def test_custom_text_query_is_escaped_and_limited_to_name_tags(self):
        phrase = 'seo"]];way["office"="it'
        query = self._searcher("custom", phrase).build_query()

        self.assertIn(json.dumps(re.escape(phrase), ensure_ascii=False), query)
        self.assertIn('nwr["name"~', query)
        self.assertIn('nwr["name:pl"~', query)
        self.assertNotIn('nwr["office"="it"]', query)
        with self.assertRaises(ValueError):
            resolve_category("custom", "x" * 101)

    def test_all_predefined_categories_have_osm_tags(self):
        self.assertEqual(
            dict(CATEGORY_CHOICES),
            {
                "it": "Firmy IT i programistyczne",
                "accountant": "Biura rachunkowe",
                "lawyer": "Kancelarie prawne",
                "architect": "Biura architektoniczne",
                "advertising_agency": "Agencje marketingowe i reklamowe",
                "estate_agent": "Biura nieruchomości",
                "insurance": "Firmy ubezpieczeniowe",
                "tax_advisor": "Doradcy podatkowi",
                "custom": "Własna kategoria",
            },
        )
        for key in (
            "it",
            "accountant",
            "lawyer",
            "architect",
            "advertising_agency",
            "estate_agent",
            "insurance",
            "tax_advisor",
        ):
            category_query = self._searcher(key).build_query()
            self.assertIn(f'nwr["office"="{key}"]', category_query)

    def test_node_filtering_uses_its_exact_coordinates(self):
        searcher = self._searcher()
        inside = searcher._normalise_element(
            {
                "type": "node",
                "id": 1,
                "lat": 1,
                "lon": 1,
                "tags": {"office": "it", "name": "Inside"},
            }
        )
        outside = searcher._normalise_element(
            {
                "type": "node",
                "id": 2,
                "lat": 3,
                "lon": 3,
                "tags": {"office": "it", "name": "Outside"},
            }
        )

        self.assertEqual(inside["latitude"], 1)
        self.assertIsNone(outside)

    def test_contact_tags_supply_website_email_phone_and_address(self):
        result = self._searcher()._normalise_element(
            {
                "type": "node",
                "id": 3,
                "lat": 1,
                "lon": 1,
                "tags": {
                    "office": "it",
                    "name": "Contact details",
                    "contact:website": "https://example.com/",
                    "contact:email": "hello@example.com",
                    "contact:phone": "+48123456789",
                    "addr:street": "Testowa",
                    "addr:housenumber": "5",
                    "addr:city": "Warszawa",
                },
            }
        )

        self.assertEqual(result["website"], "https://example.com")
        self.assertEqual(result["osm_email"], "hello@example.com")
        self.assertEqual(result["phone"], "+48123456789")
        self.assertEqual(result["address"], "Testowa 5, Warszawa")

    def test_contact_email_filters_invalid_addresses_and_uses_fallback_tag(self):
        result = self._searcher()._normalise_element(
            {
                "type": "node",
                "id": 4,
                "lat": 1,
                "lon": 1,
                "tags": {
                    "office": "it",
                    "name": "Contact details",
                    "email": "invalid..address@example.com",
                    "contact:email": "hello@example.com; also..invalid@example.com",
                },
            }
        )

        self.assertEqual(result["osm_email"], "hello@example.com")
        self.assertEqual(result["email"], "hello@example.com")

    def test_way_filtering_uses_geometry_instead_of_bbox_center(self):
        searcher = self._searcher()
        result = searcher._normalise_element(
            {
                "type": "way",
                "id": 10,
                "geometry": [
                    {"lat": 1, "lon": 1},
                    {"lat": 1, "lon": 4},
                ],
                "tags": {"office": "it", "name": "Way office"},
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual((result["latitude"], result["longitude"]), (1, 1))

    def test_relation_member_geometry_is_filtered(self):
        result = self._searcher()._normalise_element(
            {
                "type": "relation",
                "id": 20,
                "members": [
                    {
                        "type": "way",
                        "role": "outer",
                        "geometry": [
                            {"lat": 1, "lon": 1},
                            {"lat": 1, "lon": 4},
                        ],
                    }
                ],
                "tags": {"office": "it", "name": "Relation office"},
            }
        )

        self.assertEqual((result["latitude"], result["longitude"]), (1, 1))

    @patch("apps.web.web_search.httpx.post")
    def test_successful_response_is_cached(self, post):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {"elements": [{"type": "node", "id": 1}]}
        post.return_value = response
        searcher = self._searcher()

        first = searcher.search()
        second = searcher.search()

        self.assertEqual(first, second)
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["headers"]["User-Agent"],
            "GeoLeadsMailer-test/1.0",
        )

    @override_settings(
        OVERPASS_API_FALLBACK_URLS=[
            "https://overpass-fr.example/interpreter",
            "https://overpass-private.example/interpreter",
        ]
    )
    @patch("apps.web.web_search.httpx.post")
    def test_transient_failures_rotate_to_next_endpoints(self, post):
        failed = Mock(status_code=502, headers={})
        success = Mock(status_code=200, headers={})
        success.json.return_value = {"elements": [{"type": "node", "id": 2}]}
        post.side_effect = [httpx.ReadTimeout("primary timed out"), failed, success]

        result = self._searcher().search()

        self.assertEqual(result["search_mode"], "tag")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in post.call_args_list],
            [
                "https://overpass.example/interpreter",
                "https://overpass-fr.example/interpreter",
                "https://overpass-private.example/interpreter",
            ],
        )

    @override_settings(
        OVERPASS_API_FALLBACK_URLS=[
            "https://overpass-fr.example/interpreter",
            "https://overpass-private.example/interpreter",
        ]
    )
    @patch("apps.web.web_search.httpx.post")
    def test_all_endpoints_are_tried_before_reporting_failure(self, post):
        post.return_value = Mock(status_code=502, headers={})

        with self.assertRaisesRegex(OverpassAPIError, "HTTP 502"):
            self._searcher().search()

        self.assertEqual(
            [call.args[0] for call in post.call_args_list],
            [
                "https://overpass.example/interpreter",
                "https://overpass-fr.example/interpreter",
                "https://overpass-private.example/interpreter",
            ],
        )

    @patch("apps.web.web_search.time.sleep")
    @patch("apps.web.web_search.httpx.post")
    def test_rate_limit_is_retried(self, post, sleep):
        limited = Mock(status_code=429, headers={"Retry-After": "0"})
        success = Mock(status_code=200, headers={})
        success.json.return_value = {"elements": []}
        post.side_effect = [limited, success]

        self.assertEqual(
            PolygonQuery._request_elements(
                "https://overpass.example/interpreter", "query"
            ),
            [],
        )
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.0)

    @patch("apps.web.web_search.time.sleep")
    @patch("apps.web.web_search.httpx.post")
    def test_gateway_error_is_retried_then_reported(self, post, sleep):
        post.return_value = Mock(status_code=502, headers={})

        with self.assertLogs("apps.web.web_search", level="WARNING") as logs:
            with self.assertRaisesRegex(OverpassAPIError, "HTTP 502"):
                PolygonQuery._request_elements(
                    "https://overpass.example/interpreter", "query"
                )

        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(sum("retry" in message for message in logs.output), 2)

    @patch("apps.web.web_search.httpx.post")
    def test_bad_http_response_raises_clear_service_error(self, post):
        post.return_value = Mock(status_code=400, headers={})

        with self.assertRaisesRegex(OverpassAPIError, "HTTP 400"):
            PolygonQuery._request_elements(
                "https://overpass.example/interpreter", "query"
            )
