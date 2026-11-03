from django.urls import path

from . import auth_views

urlpatterns = [
    path('login', auth_views.login, name='login'),
    path('login/superuser', auth_views.login_superuser, name='login_superuser'),
    path('login/oauth', auth_views.login_oauth, name='login_oauth'),
    path(
        'login/oauth/callback',
        auth_views.login_oauth_callback,
        name='login_oauth_callback',
    ),
    path('logout', auth_views.logout, name='logout'),
    path('oauth/start', auth_views.oauth_start, name='oauth_start'),
    path('oauth/callback', auth_views.oauth_callback, name='oauth_callback'),
]
