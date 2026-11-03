from django.test import TestCase, override_settings
from django.urls import reverse
from django.apps import apps
from django.conf import settings
from django.db import connection
from unittest.mock import patch
from google.oauth2.credentials import Credentials

from apps.app.models import User, SearchQuery, Company
from apps.web.mail_send import SCOPES
from apps.web.google_oauth import credentials_from_json


@override_settings(DJANGO_SETTINGS_MODULE='apps.settings_test')
class ViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='u', email='u@example.com', password='x')

    def test_models_are_registered_from_the_single_app(self):
        self.assertEqual(apps.get_app_config('admin_app').name, 'apps.app')
        self.assertNotIn('apps.admin_app', settings.INSTALLED_APPS)
        self.assertEqual(User._meta.app_label, 'admin_app')

    def test_index_get(self):
        resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers['Referrer-Policy'],
            'strict-origin-when-cross-origin',
        )
        self.assertContains(resp, 'id="searchProgress"')
        self.assertContains(resp, 'aria-live="polite"')

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID='shared-client-id',
        GOOGLE_OAUTH_CLIENT_SECRET='shared-client-secret',
    )
    @patch('apps.web.google_oauth.Flow.from_client_config')
    def test_login_oauth_uses_shared_client_configuration(self, flow_factory):
        flow_factory.return_value.authorization_url.return_value = (
            'https://accounts.google.test/authorize',
            'oauth-state',
        )

        response = self.client.get(reverse('login_oauth'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            'https://accounts.google.test/authorize',
        )
        client_config = flow_factory.call_args.args[0]['web']
        self.assertEqual(client_config['client_id'], 'shared-client-id')
        self.assertEqual(client_config['client_secret'], 'shared-client-secret')
        self.assertFalse(hasattr(settings, 'GOOGLE_LOGIN_CLIENT_SECRETS_FILE'))

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID='shared-client-id',
        GOOGLE_OAUTH_CLIENT_SECRET='shared-client-secret',
    )
    @patch('apps.web.google_oauth.Flow.from_client_config')
    def test_gmail_oauth_stores_encrypted_token_without_client_secret(
        self,
        flow_factory,
    ):
        flow = flow_factory.return_value
        flow.credentials = Credentials(
            token='access-token-value',
            refresh_token='refresh-token-value',
            token_uri='https://oauth2.googleapis.com/token',
            client_id='shared-client-id',
            client_secret='shared-client-secret',
            scopes=SCOPES,
        )
        session = self.client.session
        session['uid'] = self.user.id
        session['oauth_state'] = 'oauth-state'
        session.save()

        response = self.client.get(
            reverse('oauth_callback'),
            {'state': 'oauth-state', 'code': 'oauth-code'},
        )

        self.assertEqual(response.status_code, 200)
        flow.fetch_token.assert_called_once()
        self.user.refresh_from_db()
        self.assertNotIn('shared-client-secret', self.user.token)
        self.assertIn('refresh-token-value', self.user.token)
        stored_credentials = credentials_from_json(self.user.token, SCOPES)
        self.assertEqual(stored_credentials.client_id, 'shared-client-id')
        self.assertEqual(stored_credentials.client_secret, 'shared-client-secret')
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT token FROM "{User._meta.db_table}" WHERE id = %s',
                [self.user.pk],
            )
            stored_token = cursor.fetchone()[0]
        self.assertNotIn('refresh-token-value', stored_token)

    @patch('apps.app.views.PolygonQuery.search')
    def test_index_post_saves_osm_results(self, mock_search):
        mock_search.return_value = {
            'polygon_search_Firmy IT i programistyczne': {
                'node/123': {
                    'osm_id': 123,
                    'osm_type': 'node',
                    'name': 'Software House',
                    'website': None,
                    'osm_email': 'hello@example.com',
                    'phone': '',
                    'address': '',
                    'category': 'office=it',
                    'osm_tags': {'office': 'it', 'name': 'Software House'},
                    'latitude': 52.1,
                    'longitude': 21.0,
                }
            },
            'search_mode': 'tag',
        }
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        resp = self.client.post(
            reverse('index'),
            data={
                'category': 'it',
                'polygon_coords': '[{"lat":52.0,"lng":20.9},'
                                  '{"lat":52.2,"lng":20.9},'
                                  '{"lat":52.2,"lng":21.1}]',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Company.objects.count(), 1)
        company = Company.objects.get()
        self.assertEqual(company.osm_id, 123)
        self.assertEqual(company.osm_email, 'hello@example.com')
        search_query = SearchQuery.objects.get()
        self.assertIn(search_query, self.user.results.all())
        self.assertIn(company, search_query.companies.all())

    @patch('apps.app.tasks.send_bulk_emails.delay')
    def test_send_email_post_queues_tasks(self, delay_mock):
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        search_query = SearchQuery.objects.create(location='Loc', query='Q')
        search_query.user.add(self.user)
        search_query.companies.add(
            Company.objects.create(
                name='Saved lead',
                email='a@x.com',
                osm_email='b@y.com',
            )
        )
        resp = self.client.post(reverse('send_email'), data={
            'location': 'Loc', 'subject': 'S', 'text': 'T', 'delay_min': 1,
            'recipients[]': ['a@x.com', 'b@y.com']
        })
        self.assertEqual(resp.status_code, 200)
        delay_mock.assert_called_once_with(
            [
                {
                    'to': 'a@x.com',
                    'subject': 'S',
                    'text': 'T',
                    'attachments': [],
                    'sender_email': self.user.email,
                },
                {
                    'to': 'b@y.com',
                    'subject': 'S',
                    'text': 'T',
                    'attachments': [],
                    'sender_email': self.user.email,
                },
            ],
            user_id=self.user.id,
            delay_s=60,
        )

    def test_send_email_get_renders_saved_locations_and_controls(self):
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        search_query = SearchQuery.objects.create(location='Saved location', query='Q')
        self.user.results.add(search_query)

        response = self.client.get(reverse('send_email'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sendEmailForm"')
        self.assertContains(response, 'id="reciver"')
        self.assertContains(response, 'Saved location')

    def test_send_email_requires_recipients(self):
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        response = self.client.post(
            reverse('send_email'),
            data={'location': 'Loc', 'subject': 'S', 'text': 'T'},
        )
        self.assertEqual(response.status_code, 400)

    def test_get_queries_for_location_requires_login(self):
        resp = self.client.get(reverse('get_queries_for_location'), data={'location': 'X'})
        self.assertEqual(resp.status_code, 401)

    def test_get_companies_for_location_query_requires_login(self):
        resp = self.client.get(reverse('get_companies_for_location_query'), data={'location': 'X', 'query': 'Q'})
        self.assertEqual(resp.status_code, 401)

    def test_get_queries_for_location_ok(self):
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        sq1 = SearchQuery.objects.create(location='X', query='Q1')
        sq2 = SearchQuery.objects.create(location='Y', query='Q2')
        self.user.results.add(sq1, sq2)
        resp = self.client.get(reverse('get_queries_for_location'), data={'location': 'X'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Q1', resp.json().get('queries', []))

    def test_get_companies_for_location_query_ok(self):
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        sq = SearchQuery.objects.create(location='X', query='Q')
        self.user.results.add(sq)
        c1 = Company.objects.create(
            name='A',
            email='a@x.com',
            osm_email='osm@x.com',
        )
        c2 = Company.objects.create(name='B', email='')
        sq.companies.add(c1, c2)
        resp = self.client.get(reverse('get_companies_for_location_query'), data={'location': 'X', 'query': 'Q'})
        self.assertEqual(resp.status_code, 200)
        companies = resp.json().get('companies', [])
        self.assertEqual(len(companies), 1)
        self.assertEqual(companies[0]['email'], 'a@x.com, osm@x.com')

    def test_get_companies_for_location_query_filters_invalid_emails(self):
        session = self.client.session
        session['uid'] = self.user.id
        session.save()
        search_query = SearchQuery.objects.create(location='Loc', query='Q')
        self.user.results.add(search_query)
        company = Company.objects.create(
            name='Example',
            email='bad..address@example.com, crawl@example.com',
            osm_email='invalid, osm@example.org',
        )
        search_query.companies.add(company)

        response = self.client.get(
            reverse('get_companies_for_location_query'),
            data={'location': 'Loc', 'query': 'Q'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['companies'],
            [{
                'id': company.pk,
                'name': 'Example',
                'email': 'crawl@example.com, osm@example.org',
            }],
        )
