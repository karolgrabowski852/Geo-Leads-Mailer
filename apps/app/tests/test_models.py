import json

from django.db import connection
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from unittest.mock import patch

from apps.app.models import User, SearchQuery, Company


@override_settings(DJANGO_SETTINGS_MODULE='apps.settings_test')
class ModelsTests(TestCase):
    def test_invalid_stored_token_fails_explicitly(self):
        user = User.objects.create(
            username="invalid-oauth-user",
            email="invalid-oauth@example.com",
            token=json.dumps({"refresh_token": "refresh-token-value"}),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE "{User._meta.db_table}" SET token = %s WHERE id = %s',
                ["not-a-fernet-token", user.pk],
            )

        with self.assertRaises(ImproperlyConfigured):
            User.objects.get(pk=user.pk)

    def test_google_oauth_token_is_encrypted_in_database(self):
        user = User.objects.create(
            username='oauth-user',
            email='oauth@example.com',
            token=json.dumps({
                'token': 'access-token-value',
                'refresh_token': 'refresh-token-value',
            }),
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT token FROM "{User._meta.db_table}" WHERE id = %s',
                [user.pk],
            )
            stored_token = cursor.fetchone()[0]

        self.assertNotIn('refresh-token-value', stored_token)
        self.assertNotIn('"refresh_token"', stored_token)
        user.refresh_from_db()
        self.assertEqual(
            json.loads(user.token),
            {
                'token': 'access-token-value',
                'refresh_token': 'refresh-token-value',
            },
        )

    def test_osm_search_results_deduplicate_by_type_and_id(self):
        user = User.objects.create(username='osm-user', email='osm@example.com')
        result = {
            'polygon_search_Firmy IT i programistyczne': {
                'node/17': {
                    'osm_type': 'node',
                    'osm_id': 17,
                    'name': 'Example IT',
                    'website': 'https://example.com',
                    'osm_email': 'osm@example.com',
                    'phone': '',
                    'address': '',
                    'category': 'office=it',
                    'osm_tags': {'office': 'it', 'name': 'Example IT'},
                    'latitude': 52.1,
                    'longitude': 21.0,
                }
            }
        }

        first = SearchQuery.save_result(
            user, 'OSM-area', 'Firmy IT i programistyczne', 0, result
        )
        second = SearchQuery.save_result(
            user, 'OSM-area', 'Firmy IT i programistyczne', 0, result
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Company.objects.count(), 1)
        company = Company.objects.get()
        self.assertEqual((company.osm_type, company.osm_id), ('node', 17))
        self.assertEqual(company.source, 'osm')
        self.assertEqual(company.website, 'https://example.com')
        self.assertEqual(company.osm_email, 'osm@example.com')
        self.assertEqual(company.email, '')

    @patch('apps.app.tasks.tasks_redis.crawl_email_addresses.apply_async')
    def test_company_email_crawl_is_queued_only_once(self, apply_async):
        company = Company.objects.create(
            name='Example',
            website='https://example.com',
        )

        self.assertTrue(company.save_mail())
        self.assertFalse(company.save_mail())

        company.refresh_from_db()
        self.assertEqual(company.email_crawl_status, 'pending')
        apply_async.assert_called_once_with(
            kwargs={'url': 'https://example.com', 'company_id': company.pk},
            queue='redis_tasks',
        )

    @patch('apps.app.tasks.tasks_redis.email_crawler.crawl_sync')
    def test_email_crawl_task_persists_extracted_addresses(self, crawl_sync):
        from apps.app.tasks.tasks_redis import crawl_email_addresses

        valid_emails = [f'contact{index}@example.com' for index in range(25)]
        crawl_sync.return_value = valid_emails + ['invalid..address@example.com']
        company = Company.objects.create(
            name='Example',
            website='https://example.com',
            osm_email='osm@example.com',
            email_crawl_status='pending',
        )

        crawl_email_addresses.run(company.website, company_id=company.pk)

        company.refresh_from_db()
        expected_emails = ', '.join(sorted(valid_emails))
        self.assertGreater(len(expected_emails), 500)
        self.assertEqual(company.email, expected_emails)
        self.assertEqual(company.osm_email, 'osm@example.com')
        self.assertEqual(company.email_crawl_status, 'completed')
