import json
import logging
import math

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.app.models import Company, SearchQuery
from apps.app.utils import save_files
from apps.web.email_validation import extract_valid_emails
from apps.web.web_search import (
    CATEGORY_CHOICES,
    OverpassAPIError,
    PolygonQuery,
    resolve_category,
)

from .auth_views import _get_current_user, session_login_required_json
from .forms import SearchForm, SendEmailForm
from .tasks import send_bulk_emails

logger = logging.getLogger(__name__)




def _validate_polygon_coords(raw_polygon):
    if not isinstance(raw_polygon, list):
        raise ValueError("The polygon coordinates must be a list of points.")
    if len(raw_polygon) < 3:
        raise ValueError("The polygon must contain at least 3 points.")
    if len(raw_polygon) > 200:
        raise ValueError("The polygon contains too many points.")

    normalized = []
    for point in raw_polygon:
        if not isinstance(point, dict):
            raise ValueError("Invalid polygon point format.")
        if "lat" not in point or "lng" not in point:
            raise ValueError("Each polygon point must contain `lat` and `lng`.")
        try:
            lat = float(point["lat"])
            lng = float(point["lng"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Polygon coordinates must be numbers.") from exc
        if (
            not math.isfinite(lat)
            or not math.isfinite(lng)
            or lat < -90
            or lat > 90
            or lng < -180
            or lng > 180
        ):
            raise ValueError("Polygon coordinates are out of range.")
        normalized.append({"lat": lat, "lng": lng})
    return normalized








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
            error = next(iter(form.errors.values()), ["Invalid search data."])
            return _error_response(str(error[0]))

        try:
            polygon_coords = _validate_polygon_coords(
                json.loads(form.cleaned_data["polygon_coords"])
            )
            category = resolve_category(
                form.cleaned_data["category"],
                form.cleaned_data["custom_category"],
            )
            language = user.language or "pl"
            country = user.country or "PL"
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
                    "Results were saved, but email extraction could not be queued "
                    "for some websites."
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
            return _error_response("Invalid polygon coordinate format.")
        except OverpassAPIError as e:
            logger.warning("Overpass search failed: %s", e)
            return _error_response(str(e), status_code=503)
        except ValueError as e:
            return _error_response(str(e))
        except Exception as e:
            logger.exception("Search or result persistence failed")
            return _error_response(
                "Could not save search results. Please try again.",
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
