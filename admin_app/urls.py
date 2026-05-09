from django.urls import path
from . import views

urlpatterns = [
    path('verify-auth-pin/', views.verify_auth_pin, name='verify_auth_pin'),
    path('login/', views.admin_login, name='admin_login'),
    path('register-admin/', views.register_admin, name='register_admin'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('generate-qr/', views.generate_qr, name='generate_qr'),
    path('download-qr-pdf/', views.download_qr_pdf, name='download_qr_pdf'),
    path('register-user/', views.register_user, name='register_user'),
    path('manage-users/', views.manage_users, name='manage_users'),
    path('manage-daily-usage/', views.manage_daily_usage, name='manage_daily_usage'),
    path('view-orders/', views.view_orders, name='view_orders'),
    path('view-payments/', views.view_payments, name='view_payments'),
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
    path('manage-qrs/delete/<str:qr_id>/', views.delete_qr_code, name='delete_qr_code'),
    path('manage-qrs/bulk-delete/', views.bulk_delete_qr_codes, name='bulk_delete_qr_codes'),
    path('regenerate-qr/<str:qr_id>/', views.regenerate_qr, name='regenerate_qr'),
    # Add these new routes for QR assignment
    path('assign-qr/', views.assign_qr, name='assign_qr'),
    path('get-user-vehicles/<str:user_id>/', views.get_user_vehicles, name='get_user_vehicles'),
    path('search-qr-codes/', views.search_qr_codes, name='search_qr_codes'),
    path('search-users/', views.search_users, name='search_users'),
    # Delete data URLs
    path('verify-delete-pin/', views.verify_delete_pin, name='verify_delete_pin'),
    path('delete-data/', views.delete_data, name='delete_data'),
    path('delete-collection/<str:collection_name>/', views.delete_collection, name='delete_collection'),
    path('delete-document/<str:collection_name>/<str:document_id>/', views.delete_document, name='delete_document'),
    path('bulk-delete/', views.bulk_delete, name='bulk_delete'),
    path('view-collection/<str:collection_name>/', views.view_collection, name='view_collection'),
    # Firebase Auth user management
    path('view-auth-users/', views.view_auth_users, name='view_auth_users'),
    path('delete-auth-user/<str:uid>/', views.delete_auth_user, name='delete_auth_user'),
    path('bulk-delete-auth-users/', views.bulk_delete_auth_users, name='bulk_delete_auth_users'),
    # Ads management URLs
    path('manage-ads/', views.manage_ads, name='manage_ads'),
    path('add-ad/', views.add_ad, name='add_ad'),
    path('update-ad/', views.update_ad, name='update_ad'),
    path('delete-ad/', views.delete_ad, name='delete_ad'),
    path('api/active-ads/<str:ad_type>/', views.get_active_ads, name='get_active_ads'),  
    # Feedback URLs
    path('feedback/', views.feedback_page, name='feedback_page'),
    path('submit-feedback/', views.submit_feedback, name='submit_feedback'),
    path('view-feedback/', views.view_feedback, name='view_feedback'),
    path('delete-feedback/<str:feedback_id>/', views.delete_feedback, name='delete_feedback'),
    path('bulk-delete-feedback/', views.bulk_delete_feedback, name='bulk_delete_feedback'), 
    path('feedback/', views.feedback_page, name='feedback_page'),
    path('submit-feedback/', views.submit_feedback, name='submit_feedback'),

    # Archive (deletion webhook + unified UI + CSV export)
    path('api/archive-deleted-user/', views.archive_deleted_user_webhook, name='archive_deleted_user_webhook'),
    path('archived/data/', views.view_archived_data, name='view_archived_data'),
    path('archived/data/export/', views.export_archived_data_csv, name='export_archived_data_csv'),
    path('archived/user/<str:user_id>/delete/', views.delete_archived_user, name='delete_archived_user'),
    path('archived/vehicle/<str:vehicle_id>/delete/', views.delete_archived_vehicle, name='delete_archived_vehicle'),
    path('archived/bulk-delete/', views.bulk_delete_archived, name='bulk_delete_archived'),
    # Legacy redirects for backward compatibility
    path('archived/users/', views.view_archived_users, name='view_archived_users'),
    path('archived/vehicles/', views.view_archived_vehicles, name='view_archived_vehicles'),
    path('archived/users/export/', views.export_archived_users_csv, name='export_archived_users_csv'),
    path('archived/vehicles/export/', views.export_archived_vehicles_csv, name='export_archived_vehicles_csv'),
    # Webhook: POST /admin/api/call — JSON did, from/caller_number, user_input (?user_input optional)
    path('api/call', views.api_call_webhook, name='api_call_webhook'),
]