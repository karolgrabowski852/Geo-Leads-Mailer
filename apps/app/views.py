import json
import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import authenticate, login as django_login, logout as django_logout, get_user_model

from apps.admin_app.models import SearchQuery, Company
from apps.app.utils import additional_user_access_to_search_query, google_search, extract_companies, save_files
from .forms import SearchForm, SendEmailForm, LoginForm
from apps.config import logger
from django.views.decorators.http import require_GET
from functools import wraps
from .tasks import send_bulk_emails
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from pathlib import Path
from django.conf import settings
from apps.web.mail_send import SCOPES
from django.core.files.base import ContentFile
from django.urls import reverse
from apps.web.web_search import PolygonQuery

GOOGLE_LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _resolve_google_login_credentials_path() -> Path:
    raw_path = Path(settings.GOOGLE_LOGIN_CLIENT_SECRETS_FILE)
    if not raw_path.is_absolute():
        raw_path = Path(settings.BASE_DIR) / raw_path
    return raw_path


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
        if lat < -90 or lat > 90 or lng < -180 or lng > 180:
            raise ValueError("Współrzędne poligonu są poza zakresem.")
        normalized.append({"lat": lat, "lng": lng})
    return normalized


def _get_current_user(request):
    if request.user.is_authenticated:
        return request.user
    return _get_session_user(request)


def _get_session_user(request):
    UserModel = get_user_model()
    uid = request.session.get('uid')
    if uid:
        try:
            return UserModel.objects.get(id=uid)
        except UserModel.DoesNotExist:
            request.session.pop('uid', None)
    return None


def session_login_required_json(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _get_current_user(request):
            return JsonResponse({'error': 'Authentication required'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def index(request):
    user = _get_current_user(request)
    if request.method == 'POST':
        if not user and not request.user.is_authenticated:
            return JsonResponse({'error': 'Login required'}, status=401)
        
        query_text = request.POST.get('query')
        polygon_coords_str = request.POST.get('polygon_coords')
        
        if not query_text or not polygon_coords_str:
            return JsonResponse({'error': 'Słowo kluczowe i obszar są wymagane'}, status=400)

        try:
            polygon_coords = _validate_polygon_coords(json.loads(polygon_coords_str))
            language = getattr(user, "language", None) or "pl"
            country = getattr(user, "country", None) or "PL"
            searcher = PolygonQuery(
                polygon_coords=polygon_coords,
                language=language,
                country=country,
            )
            searcher.set_query(query_text)
            
            results = searcher.search()
            
            return JsonResponse(results, status=200)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Błędny format współrzędnych'}, status=400)
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.error(f"Search error: {e}")
            return JsonResponse({"error": str(e)}, status=500)
            
    return render(request, 'app/index.html', {'current_user': user})

def send_email(request):
    user = _get_current_user(request)
    if not user:
        return redirect('login')
    locations = user.results.values_list('location', flat=True).distinct()
    queries = []
    companies = []

    if request.method == 'POST':
        form = SendEmailForm(request.POST, request.FILES)
        if form.is_valid():
            recipients = request.POST.getlist('recipients[]') or request.POST.getlist('reciver')
            subject = form.cleaned_data['subject']
            text = form.cleaned_data['text']
            delay_min = form.cleaned_data.get('delay_min') or 1
            upload_files = request.FILES.getlist('attachments')
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
                for r in recipients if r
            ]
            if payloads:
                send_bulk_emails.delay(payloads, user_id=user.id, delay_s=delay_s)
            return JsonResponse({"queued": len(payloads), "delay_min": delay_s // 60, "attachments": len(attachment_paths)})
        else:
            return JsonResponse({'error': 'Invalid input', 'details': form.errors}, status=400)

    return render(request, 'app/send_email.html', {
        'locations': locations,
        'queries': queries,
        'companies': companies
    })


@require_GET
@session_login_required_json
def get_queries_for_location(request):
    location = request.GET.get('location')
    user = _get_current_user(request)
    queries = user.results.filter(location=location).values_list('query', flat=True).distinct()
    logger.info(f"Queries for location {location}: {list(queries)}")
    return JsonResponse({'queries': list(queries)})


@require_GET
@session_login_required_json
def get_companies_for_location_query(request):
    location = request.GET.get('location')
    query = request.GET.get('query')
    user = _get_current_user(request)
    search_queries = user.results.filter(location=location, query=query)
    companies = (
        Company.objects
        .filter(search_queries__in=search_queries)
        .exclude(email__isnull=True)
        .exclude(email__in=['', '[]',])
        .distinct()
    )
    companies_data = [
        {'id': c.id, 'name': c.name, 'email': c.email} for c in companies
    ]
    return JsonResponse({'companies': companies_data})


def login(request):
    return render(request, 'app/login_options.html')


def login_superuser(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            django_user = authenticate(request, username=username, password=password)
            if not django_user:
                return render(request, 'app/login_superuser.html', {'error': 'Invalid credentials', 'form': form})
            if not django_user.is_superuser:
                return render(request, 'app/login_superuser.html', {'error': 'This account is not a superuser.', 'form': form})
            django_login(request, django_user)
            return redirect('index')
        else:
            return render(request, 'app/login_superuser.html', {'error': 'Invalid input', 'form': form})
    return render(request, 'app/login_superuser.html', {'form': LoginForm()})


def login_oauth(request):
    cred_path = _resolve_google_login_credentials_path()
    if not cred_path.is_file():
        return render(
            request,
            'app/login_options.html',
            {
                "error": (
                    "Google OAuth is not configured. "
                    "Missing credentials file."
                )
            },
        )

    redirect_uri = request.build_absolute_uri(reverse('login_oauth_callback'))
    flow = Flow.from_client_secrets_file(
        str(cred_path),
        scopes=GOOGLE_LOGIN_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account',
    )
    request.session['oauth_login_state'] = state
    return redirect(auth_url)


def login_oauth_callback(request):
    try:
        cred_path = _resolve_google_login_credentials_path()
        if not cred_path.is_file():
            return render(
                request,
                'app/login_options.html',
                {
                    "error": (
                        "Google OAuth is not configured. "
                        "Missing credentials file."
                    )
                },
            )

        state = request.session.pop('oauth_login_state', None)
        redirect_uri = request.build_absolute_uri(reverse('login_oauth_callback'))
        flow = Flow.from_client_secrets_file(
            str(cred_path),
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
            return render(request, 'app/login_options.html', {"error": "Google OAuth did not return an email address."})

        UserModel = get_user_model()
        django_user, _ = UserModel.objects.get_or_create(
            username=email,
            defaults={"email": email},
        )
        if not django_user.email:
            django_user.email = email
            django_user.save(update_fields=["email"])
        django_login(request, django_user)

        request.session['uid'] = django_user.id
        return redirect('index')
    except Exception as e:
        logger.error(f"Error during OAuth login callback: {e}")
        return render(request, 'app/login_options.html', {"error": "An error occurred during OAuth authentication."})


def logout(request):
    request.session.pop('uid', None)
    django_logout(request)
    return redirect('login')


def oauth_start(request):
    user = _get_current_user(request)
    if not user:
        return redirect('login')
    cred_path = getattr(user.credentials, 'path', None)
    if not cred_path or not Path(cred_path).is_file():
        return render(request, 'app/oauth.html', {"error": "No credentials file found."})

    if user.token and user.token.name and Path(user.token.path).is_file():
        try:
            creds = Credentials.from_authorized_user_file(user.token.path, SCOPES)
            if creds and creds.valid and not creds.expired:
                return redirect('send_email')
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                user.token.save(user.token.name.split('/')[-1], ContentFile(creds.to_json()), save=True)
                return redirect('send_email')
        except Exception:
            pass
    redirect_uri = request.build_absolute_uri(reverse('oauth_callback'))
    flow = Flow.from_client_secrets_file(
        cred_path,
        scopes=SCOPES,
        redirect_uri=redirect_uri  
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    request.session['oauth_state'] = state
    if request.method == 'POST':
        return redirect(auth_url)
    return render(request, 'app/oauth.html', {"auth_url": auth_url})


def oauth_callback(request):
    try:
        user = _get_current_user(request)
        if not user:
            return redirect('login')

        cred_path = getattr(user.credentials, 'path', None)
        if not cred_path or not Path(cred_path).is_file():
            return render(request, 'app/oauth.html', {"error": "No credentials file found."})

        state = request.session.pop('oauth_state', None)
        redirect_uri = request.build_absolute_uri(reverse('oauth_callback'))
        flow = Flow.from_client_secrets_file(
            cred_path,
            scopes=SCOPES,
            state=state,
            redirect_uri=redirect_uri
        )

        flow.fetch_token(authorization_response=request.build_absolute_uri())

        creds = flow.credentials
        user.token.save(f"token.json", ContentFile(creds.to_json()), save=True)
        return render(request, 'app/index.html', {"success": "OAuth successful."})

    except Exception as e:
        print(f"Error during OAuth callback: {e}")
        return render(request, 'app/login_options.html', {"error": "An error occurred during OAuth authentication."})