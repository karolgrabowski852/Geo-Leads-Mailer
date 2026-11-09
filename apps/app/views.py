import json
import logging

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.app.models import Company, SearchQuery
from apps.app.utils import (
    _validate_polygon_coords,
    is_authenticated,
    save_files,
)
from apps.web.email_validation import extract_valid_emails
from apps.web.web_search import (
    CATEGORY_CHOICES,
    OverpassAPIError,
    PolygonQuery,
    resolve_category,
)

from .forms import SearchForm, SendEmailForm
from .tasks import send_bulk_emails

logger = logging.getLogger(__name__)


def _index_authentication_required(request):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"error": "Login required"}, status=401)
    return render(
        request,
        "app/index.html",
        {
            "current_user": None,
            "categories": CATEGORY_CHOICES[:-1],
            "search_error": "Login required",
        },
        status=401,
    )


@is_authenticated(methods=("POST",), on_failure=_index_authentication_required)
def index(request, *, user):
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
            searcher = PolygonQuery(
                polygon_coords=polygon_coords,
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


@is_authenticated(on_failure=lambda _request: redirect("login"))
def send_email(request, *, user):
    searches = user.results.order_by("-searched_at", "-pk")
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
            "searches": searches,
            "companies": companies,
        },
    )


@require_GET
@is_authenticated
def get_queries_for_location(request, *, user):
    location = request.GET.get("location")
    queries = (
        user.results.filter(location=location)
        .values_list("query", flat=True)
        .distinct()
    )
    logger.info(f"Queries for location {location}: {list(queries)}")
    return JsonResponse({"queries": list(queries)})


@require_GET
@is_authenticated
def get_companies_for_location_query(request, *, user):
    location = request.GET.get("location")
    query = request.GET.get("query")
    search_queries = user.results.filter(location=location, query=query)
    companies = Company.objects.filter(search_queries__in=search_queries).filter(
        Q(email__gt="") | Q(osm_email__gt="")
    ).distinct()
    return JsonResponse({"companies": _serialize_companies(companies)})


@require_GET
@is_authenticated
def get_companies_for_search(request, *, user):
    search_id = request.GET.get("search_id", "")
    if not search_id.isdecimal():
        return JsonResponse({"error": "Invalid search."}, status=400)

    search_query = user.results.filter(pk=search_id).first()
    if search_query is None:
        return JsonResponse({"error": "Search not found."}, status=404)

    companies = search_query.companies.filter(
        Q(email__gt="") | Q(osm_email__gt="")
    ).distinct()
    return JsonResponse({"companies": _serialize_companies(companies)})


def _serialize_companies(companies):
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
    return companies_data
