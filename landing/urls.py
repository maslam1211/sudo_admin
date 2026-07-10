from django.urls import path
from . import views
from admin_app import checkout_views

urlpatterns = [
    path('', views.index, name='index'),
    path('terms/', views.terms, name='terms'),
    path('privacy/', views.privacy, name='privacy'),
    path('how-it-works/', views.how_it_works, name='how_it_works'),
    path('buy/', checkout_views.buy_now, name='buy_now'),
    path('buy/success/', checkout_views.buy_success, name='buy_success'),
    path('buy/failed/', checkout_views.buy_failure, name='buy_failure'),
    path('buy/cancelled/', checkout_views.buy_cancelled, name='buy_cancelled'),
    path('buy/pending/', checkout_views.buy_pending, name='buy_pending'),
]
