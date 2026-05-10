"""Call-bridge routes; included under /admin/ — same paths and names as before."""

from django.urls import path

from . import views

urlpatterns = [
    path('api/call/register', views.register_call_destination, name='register_call_destination'),
    path('api/call', views.api_call_webhook, name='api_call_webhook'),
]
