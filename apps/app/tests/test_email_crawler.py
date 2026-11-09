from unittest.mock import AsyncMock, Mock, patch

from django.test import SimpleTestCase

from apps.web.email_crawler import EmailCrawler


class EmailCrawlerTests(SimpleTestCase):
    def test_denies_social_media_domains_and_subdomains(self):
        crawler = EmailCrawler()

        for url in (
            "https://x.com",
            "https://www.reddit.com",
            "https://youtu.be",
            "https://web.telegram.org",
        ):
            with self.subTest(url=url):
                self.assertTrue(crawler._is_denied_domain(url))

        self.assertFalse(crawler._is_denied_domain("https://example.com"))

    def test_extract_emails_returns_only_valid_unique_addresses(self):
        html = """
            <a href="mailto:Info@example.com">Info</a>
            sales+eu@example.co.uk
            info@example.com
            invalid..address@example.com
            another@example..com
        """

        self.assertEqual(
            EmailCrawler()._extract_emails(html),
            {"Info@example.com", "sales+eu@example.co.uk"},
        )

    @patch("apps.web.email_crawler.httpx.AsyncClient")
    @patch.object(EmailCrawler, "_is_allowed", return_value=True)
    def test_crawl_fetches_website_and_returns_valid_emails(
        self, _is_allowed, async_client_class
    ):
        response = Mock(
            status_code=200,
            headers={"Content-Type": "text/html"},
            text="Contact us at info@example.com or bad..address@example.com",
        )
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.get.return_value = response
        async_client_class.return_value = client

        emails = EmailCrawler().crawl_sync("https://example.com")

        self.assertEqual(emails, ["info@example.com"])
        self.assertGreater(client.get.await_count, 0)
