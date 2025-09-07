from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.admin_login, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('generate-qr/', views.generate_qr, name='generate_qr'),
    path('download-qr-pdf/', views.download_qr_pdf, name='download_qr_pdf'),
    path('register-user/', views.register_user, name='register_user'),
    path('manage-users/', views.manage_users, name='manage_users'),
    path('view-orders/', views.view_orders, name='view_orders'),
    path('update_order_status/', views.update_order_status, name='update_order_status'),
    path('export_orders_with_qr/', views.export_orders_with_qr, name='export_orders_with_qr'),
    path('logout/', views.admin_logout, name='logout'),
    path('register-external-user/', views.external_user_registration, name='external_register'),
    path('send-notification/<str:qr_id>/', views.check_id_enabled, name='check_id_enabled'),
    path('activate-id/<str:qr_id>/', views.activate_id, name='activate_id'),
    path('send-notification-final/<str:qr_id>/', views.send_notification, name='send_notification'),
    path('send-feedback/', views.send_feedback, name='send_feedback'),
    path('send-feedback-notify/', views.send_feedback_notify, name='send_feedback_notify'),
    path('manage-qrs/', views.manage_qrs, name='manage_qrs'),
    path('regenerate-qr/<str:qr_id>/', views.regenerate_qr, name='regenerate_qr'),

]
