import logging
import re
from typing import List, Set
from urllib.parse import urljoin, urlparse
import httpx
import asyncio
from asgiref.sync import async_to_sync
import urllib.robotparser as robotparser
from collections import deque
from apps.web.email_validation import extract_valid_emails

logger = logging.getLogger(__name__)

# Heuristic keyword paths to prioritize/find likely contact pages
KEYWORD_PATHS = [
    "contact", "kontakt", "about", "o-nas", "career", "careers",
    "team", "impressum", "kariera"
]
DENYLIST_DOMAINS = {
            "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
            "tiktok.com", "youtube.com",
        }

class EmailCrawler:
    def __init__(self) -> None:
        self.client: httpx.AsyncClient | None = None
        self._robots_cache: dict[str, robotparser.RobotFileParser] = {}

    def _normalize_url(self, url: str) -> str:
        if not url.lower().startswith(("http://", "https://")):
            return f"https://{url}"
        return url

    def _domain_matches(self, host: str, domain: str) -> bool:
        host = host.lower()
        domain = domain.lower()
        return host == domain or host.endswith("." + domain)

    def _is_denied_domain(self, url: str) -> bool:
        netloc = urlparse(url).netloc
        return any(self._domain_matches(netloc, d) for d in DENYLIST_DOMAINS)

    def _get_robot(self, scheme: str, netloc: str) -> robotparser.RobotFileParser | None:
        key = netloc.lower()
        if key in self._robots_cache:
            return self._robots_cache[key]
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{scheme}://{netloc}/robots.txt")
        try:
            rp.read()
        except Exception as e:
            logger.warning(f"[crawler] robots.txt read failed for {netloc}: {e}")
        self._robots_cache[key] = rp
        return rp

    def _is_allowed(self, url: str) -> bool:
        if self._is_denied_domain(url):
            return False
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return True
        rp = self._get_robot(parsed.scheme, parsed.netloc)
        try:
            return rp.can_fetch(url) if rp else True
        except Exception:
            return True

    def _extract_emails(self, html: str) -> Set[str]:
        if not html:
            return set()
        return set(extract_valid_emails(html))

    def _discover_links(self, base_url: str, html: str) -> List[str]:
        sites = deque(maxlen=15)
        links: Set[str] = set()

        if not html:
            return list()
        for kw in KEYWORD_PATHS:
            guess = urljoin(base_url.rstrip('/') + '/', kw)
            if guess not in links and self._is_allowed(guess):
                links.add(guess)
        sites.extend(links)

        links: Set[str] = set()
        for match in re.finditer(r'href=["\']([^"\']+)["\']', html):
            href = match.group(1)
            if href.startswith('#'):
                continue
            full = urljoin(base_url, href)
            if urlparse(full).netloc == urlparse(base_url).netloc:
                candidate = full.split('#')[0]
                if self._is_allowed(candidate):
                    links.add(candidate)
        sites.extend(links)
        return list(sites)

    async def _fetch(self, url: str) -> str:
        try:
            if not self._is_allowed(url):
                logger.info(f"[crawler] disallowed by robots or denylist: {url}")
                return ""
            assert self.client is not None
            response = await self.client.get(url)
            if response.status_code == 200 and 'text/html' in response.headers.get('Content-Type', ''):
                return response.text
            return ""
        except httpx.HTTPError as e:
            logger.error(f"Error fetching {url}: {e}")
            return ""

    async def crawl(self, url: str) -> List[str]:
        if not url:
            return []
        base_url = self._normalize_url(url)
        if not self._is_allowed(base_url):
            logger.info(f"[crawler] base url disallowed: {base_url}")
            return []

        emails: Set[str] = set()
        async with httpx.AsyncClient(follow_redirects=True, timeout=2.0) as client:
            self.client = client
            html = await self._fetch(base_url)
            additional_links = self._discover_links(base_url, html)
            tasks = [self._fetch(link) for link in additional_links]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            responses.append(html)
            for resp in responses:
                if isinstance(resp, Exception):
                    logger.warning(f"[crawler] link fetch failed: {resp}")
                    continue
                emails.update(self._extract_emails(resp))
            self.client = None
        return list(emails)

    def crawl_sync(self, url: str) -> List[str]:
        return async_to_sync(self.crawl)(url)


email_crawler = EmailCrawler()