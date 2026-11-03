import json
import logging
import math
from functools import wraps

import requests
from google.auth.exceptions import GoogleAuthError
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET
from google.auth.transport.requests import Request

from apps.app.models import Company, SearchQuery
from apps.app.utils import save_files
from apps.web.mail_send import SCOPES
from apps.web.email_validation import extract_valid_emails
from apps.web.google_oauth import (
    create_google_oauth_flow,
    credentials_from_json,
    credentials_to_json,
    is_google_oauth_configured,
)
from apps.web.web_search import (
    CATEGORY_CHOICES,
    OverpassAPIError,
    PolygonQuery,
    resolve_category,
)

from .forms import LoginForm, SearchForm, SendEmailForm
from .tasks import send_bulk_emails

logger = logging.getLogger(__name__)

GOOGLE_LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _google_oauth_configuration_error(request, template_name):
    return render(
        request,
        template_name,
        {
            "error": (
                "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID "
                "and GOOGLE_OAUTH_CLIENT_SECRET on the server."
            )
        },
        status=503,
    )


def _validate_polygon_coords(raw_polygon):
    if not isinstance(raw_polygon, list):
        raise ValueError("Pole `polygon_coords` musi być listą punktów.")
    if len(raw_polygon) < 3:
        raise ValueError("Poligon musi mieć co najmniej 3 punkty.")
    if len(raw_polygon) > 200:
        raise ValueError("Poligon ma zbyt wiele punktów.")

    normalized = []
    for point in raw_polygon:
        if not isinstance(point, dict):
            raise ValueError("Niepoprawny format punktu poligonu.")
        if "lat" not in point or "lng" not in point:
            raise ValueError("Każdy punkt musi zawierać `lat` i `lng`.")
        lat = float(point["lat"])
        lng = float(point["lng"])
        if (
            not math.isfinite(lat)
            or not math.isfinite(lng)
            or lat < -90
            or lat > 90
            or lng < -180
            or lng > 180
        ):
            raise ValueError("Współrzędne poligonu są poza zakresem.")
        normalized.append({"lat": lat, "lng": lng})
    return normalized


def _get_current_user(request):
    if request.user.is_authenticated:
        return request.user
    return _get_session_user(request)


def _get_session_user(request):
    UserModel = get_user_model()
    uid = request.session.get("uid")
    if uid:
        try:
            return UserModel.objects.get(id=uid)
        except UserModel.DoesNotExist:
            request.session.pop("uid", None)
    return None


def session_login_required_json(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _get_current_user(request):
            return JsonResponse(
                {"error": "Authentication required"},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return wrapper


def index(request):
    user = _get_current_user(request)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    context = {
        "current_user": user,
        "categories": CATEGORY_CHOICES[:-1],
    }

    def _error_response(message, status_code=400):
        if is_ajax:
            return JsonResponse({"error": message}, status=status_code)
        return render(
            request,
            "app/index.html",
            {**context, "search_error": message},
            status=status_code,
        )

    if request.method == "POST":
        if not user and not request.user.is_authenticated:
            return _error_response("Login required", status_code=401)

        form = SearchForm(request.POST)
        if not form.is_valid():
            error = next(iter(form.errors.values()), ["Niepoprawne dane wyszukiwania."])
            return _error_response(str(error[0]))

        try:
            polygon_coords = _validate_polygon_coords(
                json.loads(form.cleaned_data["polygon_coords"])
            )
            category = resolve_category(
                form.cleaned_data["category"],
                form.cleaned_data["custom_category"],
            )
            language = getattr(user, "language", None) or "pl"
            country = getattr(user, "country", None) or "PL"
            searcher = PolygonQuery(
                polygon_coords=polygon_coords,
                language=language,
                country=country,
            )
            searcher.set_category(category)
            results = searcher.search()
            results["polygon_coords"] = polygon_coords
            search_query = SearchQuery.save_result(
                user=user,
                location=searcher.location_key,
                query=category.label,
                accuracy=0,
                result=results,
            )

            queue_failures = 0
            for company in search_query.companies.filter(website__isnull=False):
                try:
                    company.save_mail()
                except Exception:
                    queue_failures += 1
                    logger.exception(
                        "Could not queue email extraction for company %s",
                        company.pk,
                    )
            if queue_failures:
                results["search_warning"] = (
                    "Wyniki zapisano, ale nie udało się dodać do kolejki "
                    "ekstrakcji adresów e-mail dla części stron."
                )
            results["search_label"] = category.label

            if is_ajax:
                return JsonResponse(results, status=200)

            return render(
                request,
                "app/index.html",
                {
                    **context,
                    "search_results": results,
                    "search_query": category.label,
                },
                status=200,
            )

        except json.JSONDecodeError:
            return _error_response("Błędny format współrzędnych")
        except OverpassAPIError as e:
            logger.warning("Overpass search failed: %s", e)
            return _error_response(str(e), status_code=503)
        except ValueError as e:
            return _error_response(str(e))
        except Exception as e:
            logger.exception("Search or result persistence failed")
            return _error_response(
                "Nie udało się zapisać wyników wyszukiwania. Spróbuj ponownie.",
                status_code=500,
            )

    return render(request, "app/index.html", context)


def send_email(request):
    user = _get_current_user(request)
    if not user:
        return redirect("login")
    locations = user.results.values_list("location", flat=True).distinct()
    queries = []
    companies = []

    if request.method == "POST":
        form = SendEmailForm(request.POST, request.FILES)
        if form.is_valid():
            raw_recipients = request.POST.getlist(
                "recipients[]"
            ) or request.POST.getlist("reciver")
            email_validator = EmailValidator()
            recipients = []
            seen_recipients = set()
            for raw_recipient in raw_recipients:
                recipient = raw_recipient.strip()
                if not recipient:
                    continue
                try:
                    email_validator(recipient)
                except ValidationError:
                    return JsonResponse(
                        {"error": f"Invalid email address: {recipient}"},
                        status=400,
                    )
                normalized = recipient.casefold()
                if normalized not in seen_recipients:
                    recipients.append(recipient)
                    seen_recipients.add(normalized)
            if not recipients:
                return JsonResponse(
                    {"error": "Select at least one valid email address."},
                    status=400,
                )
            subject = form.cleaned_data["subject"]
            text = form.cleaned_data["text"]
            delay_min = form.cleaned_data.get("delay_min") or 1
            upload_files = request.FILES.getlist("attachments")
            attachment_paths: list[str] = []
            if upload_files:
                attachment_paths = save_files(upload_files)
            delay_s = max(0, int(delay_min)) * 60
            payloads = [
                {
                    "to": r,
                    "subject": subject,
                    "text": text,
                    "attachments": attachment_paths,
                    "sender_email": user.email,
                }
                for r in recipients
                if r
            ]
            if payloads:
                send_bulk_emails.delay(
                    payloads,
                    user_id=user.id,
                    delay_s=delay_s,
                )
            return JsonResponse(
                {
                    "queued": len(payloads),
                    "delay_min": delay_s // 60,
                    "attachments": len(attachment_paths),
                }
            )
        else:
            return JsonResponse(
                {"error": "Invalid input", "details": form.errors}, status=400
            )

    return render(
        request,
        "app/send_email.html",
        {
            "current_user": user,
            "locations": locations,
            "queries": queries,
            "companies": companies,
        },
    )


@require_GET
@session_login_required_json
def get_queries_for_location(request):
    location = request.GET.get("location")
    user = _get_current_user(request)
    queries = (
        user.results.filter(location=location)
        .values_list("query", flat=True)
        .distinct()
    )
    logger.info(f"Queries for location {location}: {list(queries)}")
    return JsonResponse({"queries": list(queries)})


@require_GET
@session_login_required_json
def get_companies_for_location_query(request):
    location = request.GET.get("location")
    query = request.GET.get("query")
    user = _get_current_user(request)
    search_queries = user.results.filter(location=location, query=query)
    companies = Company.objects.filter(search_queries__in=search_queries).filter(
        Q(email__gt="") | Q(osm_email__gt="")
    ).distinct()
    companies_data = []
    for company in companies:
        emails = extract_valid_emails(
            " ".join(
                email for email in (company.email, company.osm_email) if email
            )
        )
        if not emails:
            continue
        companies_data.append({
            "id": company.id,
            "name": company.name,
            "email": ", ".join(emails),
        })
    return JsonResponse({"companies": companies_data})


def login(request):
    return render(request, "app/login_options.html")


def login_superuser(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            django_user = authenticate(
                request,
                username=username,
                password=password,
            )
            if not django_user:
                return render(
                    request,
                    "app/login_superuser.html",
                    {"error": "Invalid credentials", "form": form},
                )
            if not django_user.is_superuser:
                return render(
                    request,
                    "app/login_superuser.html",
                    {
                        "error": "This account is not a superuser.",
                        "form": form,
                    },
                )
            django_login(request, django_user)
            return redirect("index")
        else:
            return render(
                request,
                "app/login_superuser.html",
                {"error": "Invalid input", "form": form},
            )
    return render(request, "app/login_superuser.html", {"form": LoginForm()})


def login_oauth(request):
    if not is_google_oauth_configured():
        return _google_oauth_configuration_error(request, "app/login_options.html")

    redirect_uri = request.build_absolute_uri(reverse("login_oauth_callback"))
    flow = create_google_oauth_flow(
        scopes=GOOGLE_LOGIN_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
    )
    request.session["oauth_login_state"] = state
    return redirect(auth_url)


def login_oauth_callback(request):
    if not is_google_oauth_configured():
        return _google_oauth_configuration_error(request, "app/login_options.html")
    try:
        state = request.session.pop("oauth_login_state", None)
        if not state:
            return render(
                request,
                "app/login_options.html",
                {"error": "Google OAuth session expired. Please try again."},
                status=400,
            )
        redirect_uri = request.build_absolute_uri(reverse("login_oauth_callback"))
        flow = create_google_oauth_flow(
            scopes=GOOGLE_LOGIN_SCOPES,
            state=state,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        creds = flow.credentials

        userinfo_response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=20,
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
        email = userinfo.get("email")
        if not email:
            return render(
                request,
                "app/login_options.html",
                {"error": "Google OAuth did not return an email address."},
            )

        UserModel = get_user_model()
        django_user, _ = UserModel.objects.get_or_create(
            username=email,
            defaults={"email": email},
        )
        if not django_user.email:
            django_user.email = email
            django_user.save(update_fields=["email"])
        django_login(request, django_user)

        request.session["uid"] = django_user.id
        return redirect("index")
    except Exception as e:
        logger.error(f"Error during OAuth login callback: {e}")
        return render(
            request,
            "app/login_options.html",
            {"error": "An error occurred during OAuth authentication."},
        )


def logout(request):
    request.session.pop("uid", None)
    django_logout(request)
    return redirect("login")


def oauth_start(request):
    user = _get_current_user(request)
    if not user:
        return redirect("login")
    if not is_google_oauth_configured():
        return _google_oauth_configuration_error(request, "app/oauth.html")
    if not settings.FIELD_ENCRYPTION_KEYS:
        return render(
            request,
            "app/oauth.html",
            {"error": "Gmail token encryption is not configured on the server."},
            status=503,
        )

    if user.token:
        try:
            creds = credentials_from_json(user.token, SCOPES)
            if creds and creds.valid and not creds.expired:
                return redirect("send_email")
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                user.token = credentials_to_json(creds)
                user.save(update_fields=["token"])
                return redirect("send_email")
        except (
            GoogleAuthError,
            KeyError,
            TypeError,
            ValueError,
            requests.RequestException,
        ) as exc:
            logger.warning(
                "Could not load or refresh Gmail OAuth token for user %s; "
                "requesting authorization again: %s",
                user.pk,
                exc,
            )
    redirect_uri = request.build_absolute_uri(reverse("oauth_callback"))
    flow = create_google_oauth_flow(
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    request.session["oauth_state"] = state
    if request.method == "POST":
        return redirect(auth_url)
    return render(request, "app/oauth.html", {"auth_url": auth_url})


def oauth_callback(request):
    if not is_google_oauth_configured():
        return _google_oauth_configuration_error(request, "app/oauth.html")
    if not settings.FIELD_ENCRYPTION_KEYS:
        return render(
            request,
            "app/oauth.html",
            {"error": "Gmail token encryption is not configured on the server."},
            status=503,
        )
    try:
        user = _get_current_user(request)
        if not user:
            return redirect("login")

        state = request.session.pop("oauth_state", None)
        if not state:
            return render(
                request,
                "app/oauth.html",
                {"error": "Google OAuth session expired. Please try again."},
                status=400,
            )

        redirect_uri = request.build_absolute_uri(reverse("oauth_callback"))
        flow = create_google_oauth_flow(
            scopes=SCOPES,
            state=state,
            redirect_uri=redirect_uri,
        )

        flow.fetch_token(authorization_response=request.build_absolute_uri())

        creds = flow.credentials
        user.token = credentials_to_json(creds)
        user.save(update_fields=["token"])
        return render(
            request,
            "app/index.html",
            {"success": "OAuth successful."},
        )

    except Exception as e:
        logger.exception("Error during Gmail OAuth callback for user %s", user.pk)
        return render(
            request,
            "app/oauth.html",
            {"error": "An error occurred during OAuth authentication."},
        )
