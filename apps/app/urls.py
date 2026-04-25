from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
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
    path('login', views.login, name='login'),
    path('login/superuser', views.login_superuser, name='login_superuser'),
    path('login/oauth', views.login_oauth, name='login_oauth'),
    path(
        'login/oauth/callback',
        views.login_oauth_callback,
        name='login_oauth_callback',
    ),
    path('logout', views.logout, name='logout'),
    path('oauth/start', views.oauth_start, name='oauth_start'),
    path('oauth/callback', views.oauth_callback, name='oauth_callback'),

]
