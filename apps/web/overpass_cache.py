import hashlib
import logging
import time
import uuid
from collections.abc import Callable

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 60 * 60
REQUEST_LOCK_KEY = "overpass:request-lock"
REQUEST_LOCK_TTL_SECONDS = 120
REQUEST_RATE_KEY = "overpass:request-rate"
REQUEST_INTERVAL_SECONDS = 1


class OverpassAPIError(RuntimeError):
    pass


class OverpassCache:
    @classmethod
    def get_or_fetch(
        cls,
        endpoints: list[str],
        query: str,
        fetch: Callable[[], list[dict]],
    ) -> list[dict]:
        cache_key = cls._cache_key(endpoints, query)
        cached = cls._read(cache_key)
        if cached is not None:
            return cached

        lock_token = uuid.uuid4().hex
        cls._acquire_request_lock(lock_token)
        try:
            cached = cls._read(cache_key)
            if cached is not None:
                return cached
            cls._wait_for_rate_limit()
            elements = fetch()
            cls._write(cache_key, elements)
            return elements
        finally:
            cls._release_request_lock(lock_token)

    @staticmethod
    def _cache_key(endpoints: list[str], query: str) -> str:
        endpoint_key = "\n".join(endpoints)
        return "overpass:query:" + hashlib.sha256(
            f"{endpoint_key}\n{query}".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _read(cache_key: str) -> list[dict] | None:
        try:
            return cache.get(cache_key)
        except Exception as exc:
            raise OverpassAPIError(
                "Could not read the search cache."
            ) from exc

    @staticmethod
    def _write(cache_key: str, elements: list[dict]) -> None:
        try:
            cache.set(cache_key, elements, timeout=CACHE_TTL_SECONDS)
        except Exception:
            logger.exception("Could not cache the Overpass response")

    @staticmethod
    def _acquire_request_lock(lock_token: str) -> None:
        lock_deadline = time.monotonic() + 5
        try:
            while not cache.add(
                REQUEST_LOCK_KEY,
                lock_token,
                timeout=REQUEST_LOCK_TTL_SECONDS,
            ):
                if time.monotonic() >= lock_deadline:
                    raise OverpassAPIError(
                        "Map search is busy. Please try again shortly."
                    )
                time.sleep(0.25)
        except OverpassAPIError:
            raise
        except Exception as exc:
            raise OverpassAPIError(
                "Could not safely start the map search."
            ) from exc

    @staticmethod
    def _wait_for_rate_limit() -> None:
        rate_deadline = time.monotonic() + 5
        try:
            while not cache.add(
                REQUEST_RATE_KEY,
                True,
                timeout=REQUEST_INTERVAL_SECONDS,
            ):
                if time.monotonic() >= rate_deadline:
                    raise OverpassAPIError(
                        "Map search is busy. Please try again shortly."
                    )
                time.sleep(0.1)
        except OverpassAPIError:
            raise
        except Exception as exc:
            raise OverpassAPIError(
                "Could not safely start the map search."
            ) from exc

    @staticmethod
    def _release_request_lock(lock_token: str) -> None:
        try:
            if cache.get(REQUEST_LOCK_KEY) == lock_token:
                cache.delete(REQUEST_LOCK_KEY)
        except Exception:
            logger.exception("Could not release the Overpass request lock")
