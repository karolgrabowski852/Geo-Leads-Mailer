import logging

import requests
from google.auth.exceptions import GoogleAuthError
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.shortcuts import redirect, render
from django.urls import reverse
from google.auth.transport.requests import Request

from apps.web.mail_send import SCOPES
from apps.web.google_oauth import (
    create_google_oauth_flow,
    credentials_from_json,
    credentials_to_json,
    is_google_oauth_configured,
)
from .forms import LoginForm
from .utils import is_authenticated

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


@is_authenticated(on_failure=lambda _request: redirect("login"))
def oauth_start(request, *, user):
    if not is_google_oauth_configured():
        return _google_oauth_configuration_error(request, "app/oauth.html")
    if not settings.SALT_KEY:
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


@is_authenticated(on_failure=lambda _request: redirect("login"))
def oauth_callback(request, *, user):
    if not is_google_oauth_configured():
        return _google_oauth_configuration_error(request, "app/oauth.html")
    if not settings.SALT_KEY:
        return render(
            request,
            "app/oauth.html",
            {"error": "Gmail token encryption is not configured on the server."},
            status=503,
        )
    try:
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
