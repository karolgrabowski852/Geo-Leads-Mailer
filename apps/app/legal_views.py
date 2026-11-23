from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET


def _legal_context() -> dict[str, str]:
    return {
        "controller_name": settings.PRIVACY_POLICY_CONTROLLER_NAME,
        "contact_email": settings.PRIVACY_POLICY_CONTACT_EMAIL,
        "effective_date": settings.PRIVACY_POLICY_EFFECTIVE_DATE,
    }


@require_GET
def privacy_policy(request):
    return render(
        request,
        "app/privacy_policy.html",
        _legal_context(),
    )


@require_GET
def terms_of_service(request):
    return render(
        request,
        "app/terms_of_service.html",
        _legal_context(),
    )
