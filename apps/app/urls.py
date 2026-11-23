from django.urls import path
from . import legal_views, views

urlpatterns = [
    path('', views.index, name='index'),
    path(
        'privacy-policy',
        legal_views.privacy_policy,
        name='privacy_policy',
    ),
    path(
        'terms-of-service',
        legal_views.terms_of_service,
        name='terms_of_service',
    ),
    path('send_email', views.send_email, name='send_email'),
    path(
        'get_queries_for_location',
        views.get_queries_for_location,
        name='get_queries_for_location',
    ),
    path(
        'get_companies_for_location_query',
        views.get_companies_for_location_query,
        name='get_companies_for_location_query',
    ),
    path(
        'get_companies_for_search',
        views.get_companies_for_search,
        name='get_companies_for_search',
    ),
]
