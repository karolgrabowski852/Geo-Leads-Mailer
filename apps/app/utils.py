from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse
import logging
import os
import uuid
import math
from functools import wraps

logger = logging.getLogger(__name__)


def _get_current_user(request):
    if request.user.is_authenticated:
        return request.user

    user_id = request.session.get("uid")
    if user_id:
        UserModel = get_user_model()
        try:
            return UserModel.objects.get(id=user_id)
        except UserModel.DoesNotExist:
            request.session.pop("uid", None)
    return None


def save_files(upload_files: list) -> list[str]:
    attachment_paths: list[str] = []
    base_dir = settings.EMAIL_ATTACHMENTS_DIR
    batch_dir = os.path.join(base_dir, uuid.uuid4().hex)
    os.makedirs(batch_dir, exist_ok=True)
    for f in upload_files:
        dest_path = os.path.join(batch_dir, f.name)
        with open(dest_path, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        attachment_paths.append(dest_path)
    return attachment_paths


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


def is_authenticated(view_func=None, *, methods=None, on_failure=None):
    def decorator(func):
        @wraps(func)
        def inner(request, *args, **kwargs):
            user = _get_current_user(request)
            if (
                user is None
                and (methods is None or request.method in methods)
            ):
                if on_failure:
                    return on_failure(request)
                return JsonResponse(
                    {"error": "Authentication required"},
                    status=401,
                )
            return func(request, *args, user=user, **kwargs)

        return inner

    if view_func is None:
        return decorator
    return decorator(view_func)