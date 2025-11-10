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
    # Add these new routes for QR assignment
    path('assign-qr/', views.assign_qr, name='assign_qr'),
    path('get-user-vehicles/<str:user_id>/', views.get_user_vehicles, name='get_user_vehicles'),
    path('search-qr-codes/', views.search_qr_codes, name='search_qr_codes'),
    path('search-users/', views.search_users, name='search_users'),
    # Delete data URLs
    path('delete-data/', views.delete_data, name='delete_data'),
    path('delete-collection/<str:collection_name>/', views.delete_collection, name='delete_collection'),
    path('delete-document/<str:collection_name>/<str:document_id>/', views.delete_document, name='delete_document'),
    path('bulk-delete/', views.bulk_delete, name='bulk_delete'),
    path('view-collection/<str:collection_name>/', views.view_collection, name='view_collection'),
    # Ads management URLs
    path('manage-ads/', views.manage_ads, name='manage_ads'),
    path('add-ad/', views.add_ad, name='add_ad'),
    path('update-ad/', views.update_ad, name='update_ad'),
    path('delete-ad/', views.delete_ad, name='delete_ad'),
    path('api/active-ads/<str:ad_type>/', views.get_active_ads, name='get_active_ads'),   
    path('feedback/', views.feedback_page, name='feedback_page'),
    path('submit-feedback/', views.submit_feedback, name='submit_feedback'),
]