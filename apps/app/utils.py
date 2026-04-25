from django.http import JsonResponse
from django.contrib.auth import get_user_model
from apps.admin_app.models import SearchQuery, Company,\
    CompanySerializer
from apps.web.web_search import PolygonQuery
from apps.config import logger, config
import os
import uuid

User = get_user_model()


def save_files(upload_files: list) -> list[str]:
    attachment_paths: list[str] = []
    base_dir = config.email_attachments_dir
    batch_dir = os.path.join(base_dir, uuid.uuid4().hex)
    os.makedirs(batch_dir, exist_ok=True)
    for f in upload_files:
        dest_path = os.path.join(batch_dir, f.name)
        with open(dest_path, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        attachment_paths.append(dest_path)
    return attachment_paths


def kilometers_to_geo_minutes(km: float) -> float:
    minutes = km / 1.852
    return max(0.25, min(minutes, 60.0))


def google_search(city: str, query: str, grid_size_km: float, user: 'User', polygon_coords: dict = None) -> SearchQuery:
    step_minutes = kilometers_to_geo_minutes(grid_size_km)
    location_search = PolygonQuery(location=city, language=user.language, country=user.country).set_query(query)
    
    if polygon_coords:
        rectangles = location_search.generate_rectangles(step_minutes=step_minutes, polygon_coords=polygon_coords)
    else:
        rectangles = location_search.generate_rectangles(step_minutes=step_minutes)
        
    result = location_search.search(rectangles)
    search_query = SearchQuery.save_result(
        user=user,
        location=city,
        query=query,
        accuracy=grid_size_km,
        result=result
    )
    return search_query


def extract_companies(search_query: SearchQuery, grid_size_km: float, current_user: 'User') -> dict:
    if not search_query.companies\
        .exclude(email__isnull=True)\
        .exclude(email='')\
        .exists() or search_query.accuracy > grid_size_km:
        logger.info(f"Updating accuracy for search query: {search_query.accuracy} -> {grid_size_km}")
        search_query.accuracy = grid_size_km
        search_query.save()
        search_query.refresh_from_db()
        logger.info(f"Updated search query accuracy: {search_query.accuracy}")
        for company in search_query.companies.all():
            if not company.email:
                company.save_mail()
        
    return {
        'search_query': f"{search_query.location}-{search_query.query}",
        'company_count': search_query.companies.count(),
        'accuracy': search_query.accuracy,
        'companies': CompanySerializer(search_query.companies.all(), many=True).data
    }

def additional_user_access_to_search_query(current_user: 'User', search_query: SearchQuery) -> None:
    try:
        if current_user not in search_query.user.all():
            search_query.user.add(current_user)
            search_query.refresh_from_db()

        if search_query not in current_user.results.all():
            current_user.results.add(search_query)
            current_user.refresh_from_db()
    except Exception as e:
        logger.error(f"[SearchQuery attach] Error attaching user {current_user.id} to search_query {search_query.id}: {e}")

