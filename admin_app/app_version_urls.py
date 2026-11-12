"""REST API for app updates, mounted at /api/v1/ (see sudo_admin/urls.py)."""
from django.urls import path

from . import app_version_views as views

urlpatterns = [
    path('app/version-check', views.api_version_check, name='api_app_version_check'),
    path('admin/app-versions', views.api_admin_app_versions, name='api_admin_app_versions'),
    path('admin/app-versions/<str:version_id>', views.api_admin_app_version_detail,
         name='api_admin_app_version_detail'),
]
