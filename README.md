# GeoLeads Mailer 1.0

## Project Description
GeoLeads Mailer is a Django application for finding businesses in a drawn map area, extracting website email addresses, and sending email through Gmail. Business search uses OpenStreetMap data queried through Overpass API.

## Project Structure
- **apps/app/**: The Django application, including configurations, models, admin, views, and tests.
- **apps/web/**: Modules responsible for email processing, website crawling, and Overpass searches.
- **uploads/**: Temporary email attachments shared with background workers.

The application code is consolidated under `apps/app/`. Its Django model label is `admin_app`, which is used by the configured user model and migrations.

## Requirements
- Python 3.10+
- Django
- Celery
- RabbitMQ
- Redis
- Docker (optional)

## Google OAuth

Configure one Google OAuth client of type **Web application** using
`GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in the deployment
environment or a secrets manager. Register both application callbacks as
authorized redirect URIs: `/login/oauth/callback` and `/oauth/callback` on the
public application origin. Users sign in with Google and separately authorize
Gmail sending; they do not upload OAuth credential files.

Gmail refresh tokens are encrypted in PostgreSQL with
[`django-fernet-encrypted-fields`](https://pypi.org/project/django-fernet-encrypted-fields/).
Set `FIELD_ENCRYPTION_SALT_KEYS` and `DJANGO_SECRET_KEY` outside the database
and keep them stable so stored tokens remain readable.

## Application Flow

Below is a simplified ASCII diagram showing the flow of the application:

```
+----------------+       +----------------+       +----------------+
|  User Input    | --->  |  Django Views  | --->  |  Celery Tasks  |
+----------------+       +----------------+       +----------------+
        |                        |                        |
        v                        v                        v
+----------------+       +----------------+       +----------------+
|  Database      | <-->  | RabbitMQ Queue |       |  Email Sender  |
+----------------+       +----------------+       +----------------+
```

This diagram illustrates the following steps:
1. **User Input**: Data is provided by the user through the frontend.
2. **Django Views**: The backend processes the input and triggers tasks.
3. **Celery Tasks**: Background tasks are queued and executed asynchronously.
4. **Database**: Data is stored or retrieved as needed.
5. **Queues**: RabbitMQ schedules email sending, while Redis queues website email extraction.
6. **Email Sender**: Emails are sent to the leads at regular intervals to ensure higher delivery reliability.

## OpenStreetMap business search

The map sends its polygon to Django. The backend queries Overpass API with the polygon's bounding box, then filters returned nodes, ways, and relations against the exact polygon using their OSM geometry. It does not use a way/relation bounding-box center as a business location. Search results are stored in PostgreSQL and deduplicated by OSM type and ID; available websites are queued once for email extraction through the existing Redis-backed Celery worker.

The selectable categories use these documented OSM tags:

| Category | OSM tag |
| --- | --- |
| Firmy IT i programistyczne | [`office=it`](https://wiki.openstreetmap.org/wiki/Tag:office%3Dit) |
| Biura rachunkowe | [`office=accountant`](https://wiki.openstreetmap.org/wiki/Tag:office%3Daccountant) |
| Kancelarie prawne | [`office=lawyer`](https://wiki.openstreetmap.org/wiki/Tag:office%3Dlawyer) |
| Biura architektoniczne | [`office=architect`](https://wiki.openstreetmap.org/wiki/Tag:office%3Darchitect) |
| Agencje marketingowe i reklamowe | [`office=advertising_agency`](https://wiki.openstreetmap.org/wiki/Tag:office%3Dadvertising_agency) |
| Biura nieruchomości | [`office=estate_agent`](https://wiki.openstreetmap.org/wiki/Tag:office%3Destate_agent) |
| Firmy ubezpieczeniowe | [`office=insurance`](https://wiki.openstreetmap.org/wiki/Tag:office%3Dinsurance) |
| Doradcy podatkowi | [`office=tax_advisor`](https://wiki.openstreetmap.org/wiki/Tag:office%3Dtax_advisor) |

Custom phrases such as “software house” map to a known tag when an alias exists; “drukarnie” maps to the documented [`shop=printing`](https://wiki.openstreetmap.org/wiki/Tag:shop%3Dprinting). Otherwise, a length-limited, escaped text search is performed against OSM names and is identified as a text search in the results. Queries use `overpass-api.de` by default and rotate through the configured fallback instances after transient network, HTTP 429, or HTTP 5xx errors. The default fallback list includes the [French Overpass instance](https://overpass.openstreetmap.fr/) and Private.coffee; configure `OVERPASS_API_URL` and the comma-separated `OVERPASS_API_FALLBACK_URLS` to change the order. Public instances do not guarantee uptime. Successful queries are cached for six hours, uncached requests are serialized and spaced at least one second apart through the configured Django cache, and each response is limited to 500 objects.

OSM tags and contact details are stored separately from email addresses extracted from websites. The map and search results display OpenStreetMap attribution. The browser map uses the canonical `tile.openstreetmap.org` URL and a cross-origin referrer policy compatible with the OSM tile usage policy. OpenStreetMap data is available under the [Open Database License (ODbL)](https://www.openstreetmap.org/copyright); review the license terms when redistributing or building upon stored data.

Category references: [OSM office key](https://wiki.openstreetmap.org/wiki/Key:office), [Overpass QL](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL), and [Taginfo office tag statistics](https://taginfo.openstreetmap.org/keys/office#values). The Taginfo counts reviewed for this implementation are worldwide totals; a Poland-only tag count was not available from the `tag/stats` endpoint.
