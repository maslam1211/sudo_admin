import base64
import datetime
import uuid, os
import secrets
import string
import json

from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
import firebase_admin
from firebase_admin import credentials, firestore, messaging, auth
from google.cloud.firestore_v1 import FieldFilter
import qrcode
from io import BytesIO
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import send_mail
from dotenv import load_dotenv
from .serializers import CallWebhookSerializer
# from google.cloud import firestore



# Load environment variables from .env file
load_dotenv()

# Ensure Firebase is initialized only once
if not firebase_admin._apps:
    # Load Firebase credentials from the environment variables
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": "sudo-70852",
        "private_key_id": "5764dd9f77c53703fbc857b21cd625d3e93b42a3",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCz4LIxKDpylIlk\n9wcy5AZ5s0BhPFjqw009T2/fgIHAqPR7cra8ltQinjfyJb3u5aOR6yIPU67AjDgI\ne3Ry8egy0E7S2qejbpZRviPbWPJoROjoUW6LHFoS/tb6BKDpqauVl0s5eI1EVmbC\nMy8bjgTRHmFw/W+N8B3uKPEUgvV186hYzndcadXeEhVN+f3S+rf6Uhouba70Li0T\npc05bijbGkvZYPdjy8Ged2XFd9Y0rFqlrNMM3jOEhvYZs55Vb9Kp3r98uzys2WfH\ni8h4sdy2sXq0AAHQ+rS1juoZgTPZkMeFKqURB8+37a49R5BUBdpfeTDPHaffQUqb\nwJRwUoBpAgMBAAECggEAC8Tn489+A4E0fCatkebZhZz02WfZaYLdyuUnrLf7xV9I\nn8shqbU0rA8uGeneQ4NC8Ikx8U7IYFDMWcG6HMs3Jhv7DFDCJy9VJoQKVI+9TJU1\np/2r/e4c9qE176Xd4Wv4jhEYGuqIU7BTiOFQc70XE5epSHtMkTzkuHB1VaI77Tun\n3Ely7v4uALkzkJF96ZbzPlCyvMsUHvIzFu0a3Eq/xcWCgku9BLl0ELDGmvDkptUv\nQ3AJHf6eA3ieKoXrW6JsbPec5kVq94skEtR/ZZZ1l2P6Uho7psIJJOqgOro8iSyH\nVQ5+C+q+AvSCl4HBseYVEBrpACFy+utkgm4ToNYjAQKBgQDogKVfHuwXMK2RlYP2\nuMsBPgtRPk+nhGdwLP3wIE7MKjHZLitaXs6C9/ELC7A1AP3RfluvH7kqFHoZ5htW\nVBscg0a+vtFssK5oID0vp6jQEMDxiy5IF+HLcUipvC3DDAXXh12AIAlkhqRsO2CR\nearNSVVLiE3w2JebLZjovcWbGwKBgQDGDoe1WSBP79QFDDgHZVvX2pu8q3i4goDi\nkKyIejhuzyjopom2yGx7LeCqQ9bwBjLyqy4As16Wr6eCORUQgmsn29heeujIhk+P\nDuoqXRqIAB1UQlaivQ5o2gT9LeUoAJVqKllgf8CxD7PpaM6QyLKEHr0knhFwjmba\ni5zNMfemywKBgQCV3Q47MNBW5k6Kj4g/CL/5bgeXd4WaYbLW0HliRUDlQrFc3vCc\n0I1mR/D8AK20jI4OcdchG16b7BUECplGXPIYv9li69ZLq9rPTTCDPhuG+bWUO/U6\nDQLCwqNmnOAWX/KICT3Qb1X+kPb8uI03V+graIBtLk+m1cVrBcoRAvmTTwKBgGiH\nsK5Q3NHztQX4/fVBVKjnEv0PzwYqspVhX/4j63boVSH9C3/x5fdZLlMOvPkvfGJB\nYGU0Rf7ntFPxhqGRA7cku9yZqBR1drX9XC+BtggDb3dSD+GSQHGsZ6esOl7TeAhx\nU3yv0GZi8ESHcUZO9pDunEsgNfoe3kAIIXjXH2rjAoGANnqHBwQZzRMdWLnq9iRo\nF1tuj8r+REkFjHiHmYeMFJ31+VV4/yJNkqw3QqHWx9p9T4J69U/DVskZy7pklL+0\nt7TSeGgrK6cyYSAUa2MxIftdh/fXnnTCzpbazADROPLD61cCxZSRqWgZuqSdOXtA\nwD0e4Odss2x6PGrtnt0H5YA=\n-----END PRIVATE KEY-----",
        "client_email": "firebase-adminsdk-efv01@sudo-70852.iam.gserviceaccount.com",
        "client_id": "114274654285356877826",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-efv01%40sudo-70852.iam.gserviceaccount.com",
        "universe_domain": "googleapis.com",
    })

    # Initialize the Firebase app
    firebase_admin.initialize_app(cred)
    
# Now you can use Firebase as usual
db = firestore.client()

def custom_404(request, exception):
    return render(request, '404.html', status=404)

def verify_auth_pin(request):
    """PIN verification page for login/register access"""
    if request.method == 'POST':
        pin = request.POST.get('pin', '').strip()
        if pin == '4455':
            request.session['auth_pin_verified'] = True
            action = request.POST.get('action', 'login')
            if action == 'register':
                return redirect('register_admin')
            else:
                return redirect('admin_login')
        else:
            messages.error(request, 'Invalid PIN. Please try again.')
    
    return render(request, 'verify_auth_pin.html', {
        'action': request.GET.get('action', 'login')
    })

def admin_login(request):
    # Check PIN verification
    if not request.session.get('auth_pin_verified'):
        return redirect(f'/admin/verify-auth-pin/?action=login')
    
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        # Verify password
        if password != 'Sudo@123':
            messages.error(request, 'Invalid email or password.')
            return render(request, 'login.html')
        
        # Fetch user data from Firebase
        db = firestore.client()
        user_ref = db.collection('users').where(filter=FieldFilter('emailAddress', '==', email)).stream()

        user_found = False
        for user in user_ref:
            user_data = user.to_dict()
            user_found = True
            
            # Check if user has role 1 (admin role)
            if user_data.get('roleId') != 1:
                messages.error(request, "You don't have permission to access admin panel.")
                break
            
            # For role 1 users, verify email
            if user_data.get('emailAddress') == email:
                request.session['admin'] = True
                request.session['user_id'] = user.id  # Store user ID in session
                request.session['email'] = email  # Store email in session
                # Clear PIN verification after successful login
                request.session.pop('auth_pin_verified', None)
                return redirect('dashboard')
            else:
                messages.error(request, 'Invalid email or password.')
                break
        
        if not user_found:
            messages.error(request, 'No user found with this email.')
    
    return render(request, 'login.html')

def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')


from datetime import datetime, timedelta
import pytz
from django.core.cache import cache
from django.utils.timezone import now

def dashboard(request):
    if not request.session.get('admin'):
        return redirect('admin_login')

    ADMIN_EMAIL = "sudotagonline@gmail.com"
    ist = pytz.timezone('Asia/Kolkata')
    
    # Use Django's timezone-aware now()
    today = now().astimezone(ist).date()
    week_ago = today - timedelta(days=7)
    
    # Try to get cached data first (cache for 2 minutes)
    cache_key = 'dashboard_stats'
    cached_data = cache.get(cache_key)
    
    # Fetch all orders once - use this for all calculations
    orders_ref = db.collection('orders')
    try:
        # Get more orders for accurate stats (1000 for better coverage)
        # Try ordered query first, fallback to unordered
        try:
            all_orders_docs = list(orders_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1000).stream())
        except:
            all_orders_docs = list(orders_ref.limit(1000).stream())
    except:
        all_orders_docs = []
    
    # Process all orders into a list with IDs
    all_orders = []
    for doc in all_orders_docs:
        order_data = doc.to_dict()
        order_data['id'] = doc.id
        all_orders.append(order_data)
    
    # Sort by timestamp (newest first) for recent orders display
    all_orders.sort(key=lambda x: str(x.get('timestamp', '')), reverse=True)
    recent_orders = all_orders[:10]  # Get top 10 for display
    
    # Optimized: Use efficient queries with limits
    # Users count - sample approach for speed
    try:
        users_sample = list(db.collection('users').limit(1000).stream())
        users_count = sum(1 for doc in users_sample if doc.to_dict().get('emailAddress') != ADMIN_EMAIL)
        # If we got less than 1000, we have exact count
        if len(users_sample) < 1000:
            # Exact count
            pass
        else:
            # Estimate - scale up (rough approximation)
            admin_count = sum(1 for doc in users_sample if doc.to_dict().get('emailAddress') == ADMIN_EMAIL)
            if admin_count > 0:
                scale = len(users_sample) / admin_count if admin_count > 0 else 1
                users_count = int(users_count * min(scale, 10))  # Cap scaling
    except:
        users_count = 0
    
    # Helper function to parse timestamp and get date
    def get_order_date(order):
        """Extract date from order timestamp"""
        ts_value = order.get('timestamp')
        if ts_value is None:
            return None
        
        # Handle datetime objects - use the imported datetime class
        # datetime is imported as: from datetime import datetime, timedelta
        if hasattr(ts_value, 'date') and hasattr(ts_value, 'astimezone'):
            # It's a datetime object
            dt = ts_value.astimezone(ist) if ts_value.tzinfo else ist.localize(ts_value)
            return dt.date()
        
        # Handle Firestore timestamp
        if hasattr(ts_value, 'to_datetime'):
            try:
                dt = ts_value.to_datetime()
                dt = dt.astimezone(ist) if dt.tzinfo else ist.localize(dt)
                return dt.date()
            except:
                pass
        
        # Handle string timestamps - format: "November 20, 2025 at 9:46:24 PM UTC+5:30"
        if isinstance(ts_value, str):
            import re
            # Method 1: Extract date using regex (most reliable for this format)
            try:
                # Pattern: "November 20, 2025 at 9:46:24 PM UTC+5:30"
                date_match = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})', ts_value)
                if date_match:
                    month_str, day, year = date_match.groups()
                    month_map = {
                        'January': 1, 'February': 2, 'March': 3, 'April': 4,
                        'May': 5, 'June': 6, 'July': 7, 'August': 8,
                        'September': 9, 'October': 10, 'November': 11, 'December': 12
                    }
                    month = month_map.get(month_str.title(), 1)
                    return datetime(int(year), month, int(day)).date()
            except Exception as e:
                pass
            
            # Method 2: Try parsing with datetime.strptime
            try:
                # Handle UTC+5:30 format - replace with proper timezone format
                ts_clean = ts_value.replace('UTC+5:30', '+05:30').replace('UTC+0530', '+05:30')
                ts_clean = ts_clean.replace('UTC-5:30', '-05:30').replace('UTC-0530', '-05:30')
                
                formats = [
                    "%B %d, %Y at %I:%M:%S %p %z",  # With timezone like +05:30
                    "%B %d, %Y at %I:%M:%S %p",     # Without timezone
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S%z",
                ]
                for fmt in formats:
                    try:
                        dt = datetime.strptime(ts_clean, fmt)
                        if dt.tzinfo:
                            dt = dt.astimezone(ist)
                        else:
                            dt = ist.localize(dt)
                        return dt.date()
                    except:
                        continue
            except:
                pass
        
        return None
    
    # Calculate today's and week's stats from the orders we already fetched
    today_orders_list = []
    week_orders_list = []
    
    for order in all_orders:
        order_date = get_order_date(order)
        if order_date:
            if order_date == today:
                today_orders_list.append(order)
            if order_date >= week_ago:
                week_orders_list.append(order)
    
    today_orders_count = len(today_orders_list)
    today_earnings = sum(
        float(order.get('amount', 0) or 0) 
        for order in today_orders_list 
        if order.get('paymentStatus') == 'paid'
    )
    week_orders_count = len(week_orders_list)
    
    # Total orders and earnings - use the orders we already loaded
    try:
        total_orders_count = len(all_orders)
        
        # Calculate stats from all orders
        status_counts = {status: 0 for status in STATUS_MAPPING.keys()}
        total_earnings = 0
        
        for order in all_orders:
            status = order.get('orderStatus', 0)
            if status in status_counts:
                status_counts[status] = status_counts.get(status, 0) + 1
            if order.get('paymentStatus') == 'paid':
                total_earnings += float(order.get('amount', 0) or 0)
    except:
        total_orders_count = 0
        status_counts = {status: 0 for status in STATUS_MAPPING.keys()}
        total_earnings = 0
    
    # QR Codes - efficient queries
    try:
        qr_ref = db.collection('qrcodes')
        # Get active count
        active_qr_docs = list(qr_ref.where(filter=FieldFilter('isAssigned', '==', True)).limit(1000).stream())
        active_qr = len(active_qr_docs)
        
        # Get total count
        total_qr_docs = list(qr_ref.limit(1000).stream())
        total_qr = len(total_qr_docs)
        
        inactive_qr = total_qr - active_qr
    except:
        total_qr = 0
        active_qr = 0
        inactive_qr = 0
    
    context = {
        'total_users': users_count,
        'total_orders': total_orders_count,
        'today_orders': today_orders_count,
        'week_orders': week_orders_count,
        'status_counts': status_counts,
        'total_earnings': total_earnings,
        'today_earnings': today_earnings,
        'total_qr': total_qr,
        'active_qr': active_qr,
        'inactive_qr': inactive_qr,
        'STATUS_MAPPING': STATUS_MAPPING,
        'all_orders': recent_orders,
    }
    
    # Cache only non-time-sensitive stats (exclude today's and week's data)
    cache_stats = {
        'total_users': users_count,
        'total_orders': total_orders_count,
        'status_counts': status_counts,
        'total_earnings': total_earnings,
        'total_qr': total_qr,
        'active_qr': active_qr,
        'inactive_qr': inactive_qr,
        'STATUS_MAPPING': STATUS_MAPPING,
    }
    cache.set(cache_key, cache_stats, 120)
    
    return render(request, 'dashboard.html', context)

    
from django.shortcuts import render, redirect
from io import BytesIO
import qrcode
import base64
import uuid
import datetime
from django.http import HttpResponse
from PIL import Image as PILImage, ImageDraw, ImageFont
import os
from django.conf import settings

def get_font(font_size=20):
    """Helper function to get a font with fallback options"""
    try:
        # Try built-in default font first
        try:
            return ImageFont.truetype("arial.ttf", font_size)
        except:
            # Try common system font paths
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
                "/Library/Fonts/Arial.ttf",  # macOS
                "C:/Windows/Fonts/arial.ttf",  # Windows
                os.path.join(settings.BASE_DIR, 'static', 'fonts', 'arial.ttf'),
                os.path.join(settings.BASE_DIR, 'sudo_admin', 'static', 'fonts', 'arial.ttf')
            ]
            
            for path in font_paths:
                if os.path.exists(path):
                    return ImageFont.truetype(path, font_size)
            
            # Final fallback to default font
            return ImageFont.load_default()
    except Exception as e:
        print(f"Font loading error: {str(e)}")
        return ImageFont.load_default()

from django.utils.timezone import now  # Add this import at the top of your file


def generate_qr(request):
    if not request.session.get('admin'):
        return redirect('admin_login')
    
    if request.method == 'POST':
        qr_type = request.POST.get('qr_type', 'user')
        qr_data = []
        base_domain = settings.BASE_DOMAIN
        
        if qr_type == 'user':
            count = int(request.POST.get('count', 1))
            batch = db.batch()  # Firestore batch
            template_path = os.path.join(settings.BASE_DIR, 'sudo_admin', 'static', 'images', 'qr_template.jpg')
            
            if not os.path.exists(template_path):
                return render(request, 'generate_qr.html', {
                    'error': f'Template image not found at: {template_path}'
                })
            
            template_img = PILImage.open(template_path).convert('RGB')
            template_width, template_height = template_img.size
            qr_size = (int(template_height * 0.75), int(template_height * 0.75))
            left_margin = int(template_width * 0.07)
            
            for _ in range(count):
                try:
                    # Generate unique QR ID
                    qr_id = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8')[:16]
                    
                    # Create QR code
                    qr = qrcode.QRCode(
                        version=3,
                        error_correction=qrcode.constants.ERROR_CORRECT_H,
                        box_size=12,
                        border=2
                    )
                    qr.add_data(f"{base_domain}/admin/send-notification/{qr_id}/")
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="#dcbd1f", back_color="#161416")
                    
                    # Paste on template
                    qr_img = qr_img.resize(qr_size, PILImage.Resampling.LANCZOS)
                    final_img = template_img.copy()
                    qr_position = (
                        left_margin,
                        (template_height - qr_size[1]) // 2
                    )
                    final_img.paste(qr_img, qr_position)
                    
                    # Convert to base64
                    buffer = BytesIO()
                    final_img.save(buffer, format="PNG")
                    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    # Prepare Firestore data
                    qr_doc_ref = db.collection('qrcodes').document(qr_id)
                    qr_data_firestore = {
                        'createdBy': 'admin',
                        'createdDateTime': now(),
                        'isAssigned': False,
                        'qrId': qr_id,
                        'vehicleID': '',
                        'userID': ''
                    }
                    batch.set(qr_doc_ref, qr_data_firestore)
                    
                    # Add to response
                    qr_data.append({
                        'type': 'user',
                        'qrId': qr_id,
                        'vehicleID': '',
                        'qr_code_base64': qr_code_base64
                    })
                except Exception as e:
                    # Log error but continue
                    qr_data.append({'error': f'Failed to generate QR: {str(e)}'})
            
            # Commit batch to Firestore
            try:
                batch.commit()
            except Exception as e:
                return render(request, 'generate_qr.html', {
                    'error': f'Failed to save QR codes to Firestore: {str(e)}'
                })
        
        else:
            # External QR generation
            count = int(request.POST.get('external_count', 1))
            registration_url = f"{base_domain}/register-external-user/"
            
            for _ in range(count):
                try:
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_H,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(registration_url)
                    qr.make(fit=True)
                    qr_img = qr.make_image(fill_color="black", back_color="white")
                    
                    buffer = BytesIO()
                    qr_img.save(buffer, format="PNG")
                    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    qr_data.append({
                        'type': 'external',
                        'qr_code_base64': qr_code_base64
                    })
                except Exception as e:
                    qr_data.append({'error': f'Failed to generate external QR: {str(e)}'})

        request.session['qr_data'] = qr_data
        return render(request, 'generate_qr.html', {'qr_data': qr_data})

    return render(request, 'generate_qr.html')

# def download_qr_pdf(request):
#     if not request.session.get('admin') or 'qr_data' not in request.session:
#         return redirect('admin_login')

#     qr_data = request.session.get('qr_data', [])
#     response = HttpResponse(content_type='application/pdf')
#     response['Content-Disposition'] = 'attachment; filename="qr_codes.pdf"'

#     from reportlab.lib.pagesizes import letter
#     from reportlab.platypus import SimpleDocTemplate, Image, Paragraph, Spacer, Table, TableStyle, PageBreak
#     from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
#     from reportlab.lib import colors
#     from reportlab.lib.units import inch
#     import io
#     import pytz

#     buffer = io.BytesIO()
#     # Set minimal margins for maximum width
#     doc = SimpleDocTemplate(buffer, pagesize=letter,
#                           leftMargin=0.3*inch,  # Reduced margins
#                           rightMargin=0.3*inch,
#                           topMargin=0.4*inch,
#                           bottomMargin=0.4*inch)
#     elements = []

#     # Custom styles
#     title_style = ParagraphStyle(
#         name="Title",
#         fontSize=14,
#         alignment=1,  # CENTER
#         fontName="Helvetica-Bold",
#         spaceAfter=4,
#         textColor=colors.black
#     )
    
#     date_style = ParagraphStyle(
#         name="Date",
#         fontSize=10,
#         alignment=1,  # CENTER
#         fontName="Helvetica",
#         spaceAfter=12,
#         textColor=colors.darkgrey
#     )
    
#     qr_id_style = ParagraphStyle(
#         name="QR_ID",
#         fontSize=12,
#         alignment=1,  # CENTER
#         fontName="Helvetica-Bold",
#         spaceBefore=12,  # Increased padding above ID
#         textColor=colors.black
#     )

#     # Title and date (only on first page)
#     elements.append(Paragraph("Generated QR Codes", title_style))
#     ist = pytz.timezone('Asia/Kolkata')
#     current_datetime = now().astimezone(ist)
#     date_time_string = current_datetime.strftime("%A, %B %d, %Y - %I:%M %p")
#     elements.append(Paragraph(f"Created on: {date_time_string}", date_style))
#     elements.append(Spacer(1, 24))

#     # Calculate maximum possible width (90% of available space)
#     page_width = letter[0] - doc.leftMargin - doc.rightMargin
#     qr_width = min(4.0*inch, page_width * 0.9)  # Wider format (max 4 inches)
#     qr_height = qr_width * 0.5  # Maintain aspect ratio (2:1 width:height)
#     items_per_page = 3  # 3 QR codes per page

#     for i, qr in enumerate(qr_data):
#         if i > 0 and i % items_per_page == 0:
#             elements.append(PageBreak())
#             # Reset margins for new page
#             doc.leftMargin = 0.3*inch
#             doc.rightMargin = 0.3*inch

#         # Create extra wide QR code image
#         qr_img = Image(BytesIO(base64.b64decode(qr['qr_code_base64'])),
#                       width=qr_width, height=qr_height)
        
#         # Create ID text with padding
#         qr_id = Paragraph(qr.get('qrId', ''), qr_id_style)
        
#         # Create content with proper spacing
#         content_table = Table([
#             [qr_img],
#             [Spacer(1, 8)],  # Additional padding
#             [qr_id]
#         ], colWidths=qr_width)
        
#         content_table.setStyle(TableStyle([
#             ('ALIGN', (0,0), (-1,-1), 'CENTER'),
#             ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
#             ('LEFTPADDING', (0,0), (-1,-1), 0),
#             ('RIGHTPADDING', (0,0), (-1,-1), 0),
#             ('BOTTOMPADDING', (0,0), (-1,-1), 0),
#         ]))
        
#         elements.append(content_table)
#         elements.append(Spacer(1, 24))  # Space between QR sets

#     doc.build(elements)
#     pdf = buffer.getvalue()
#     buffer.close()
#     response.write(pdf)
#     return response

def download_qr_pdf(request):
    if not request.session.get('admin') or 'qr_data' not in request.session:
        return redirect('admin_login')

    qr_data = request.session.get('qr_data', [])
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="qr_codes.pdf"'

    from reportlab.lib.pagesizes import letter, A5, A6, landscape
    from reportlab.platypus import SimpleDocTemplate, Image, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    import io
    import pytz

    buffer = io.BytesIO()
    
    # Use A5 size (half of A4) which is perfect for single QR codes
    # You can also try: A6 (quarter of A4) or custom size like (4*inch, 6*inch)
    page_size = A5  # Options: A5, A6, or custom (width, height)
    
    # For portrait orientation (taller than wide)
    doc = SimpleDocTemplate(buffer, pagesize=page_size,
                          leftMargin=0.5*inch,
                          rightMargin=0.5*inch,
                          topMargin=0.5*inch,
                          bottomMargin=0.5*inch)
    
    elements = []

    # Custom styles
    title_style = ParagraphStyle(
        name="Title",
        fontSize=14,
        alignment=1,  # CENTER
        fontName="Helvetica-Bold",
        spaceAfter=4,
        textColor=colors.black
    )
    
    date_style = ParagraphStyle(
        name="Date",
        fontSize=10,
        alignment=1,  # CENTER
        fontName="Helvetica",
        spaceAfter=12,
        textColor=colors.darkgrey
    )
    
    qr_id_style = ParagraphStyle(
        name="QR_ID",
        fontSize=12,
        alignment=1,  # CENTER
        fontName="Helvetica-Bold",
        spaceBefore=12,
        textColor=colors.black
    )

    # Title and date (only on first page)
    elements.append(Paragraph("Generated QR Codes", title_style))
    ist = pytz.timezone('Asia/Kolkata')
    current_datetime = now().astimezone(ist)
    date_time_string = current_datetime.strftime("%A, %B %d, %Y - %I:%M %p")
    elements.append(Paragraph(f"Created on: {date_time_string}", date_style))
    elements.append(Spacer(1, 20))

    # Adjust QR size for the smaller page
    page_width = page_size[0] - doc.leftMargin - doc.rightMargin
    page_height = page_size[1] - doc.topMargin - doc.bottomMargin
    
    # Make QR code fit nicely on the smaller page
    qr_width = min(3.5*inch, page_width * 0.8)  # Slightly smaller for A5
    qr_height = qr_width * 0.5  # Maintain aspect ratio

    for i, qr in enumerate(qr_data):
        if i > 0:  # Add page break for all QR codes except the first one
            elements.append(PageBreak())

        # Create QR code image
        qr_img = Image(BytesIO(base64.b64decode(qr['qr_code_base64'])),
                      width=qr_width, height=qr_height)
        
        # Create ID text with padding
        qr_id = Paragraph(qr.get('qrId', ''), qr_id_style)
        
        # Create content with proper spacing
        content_table = Table([
            [qr_img],
            [Spacer(1, 8)],  # Additional padding
            [qr_id]
        ], colWidths=qr_width)
        
        content_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        
        elements.append(content_table)
        elements.append(Spacer(1, 20))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

def register_user(request):
    if not request.session.get('admin'):
        return redirect('admin_login')
    users = db.collection('users').stream()
    user_list = [{'userId': user.id, **user.to_dict()} for user in users]
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        updated_data = {
            'firstname': request.POST.get('firstname'),
            'lastName': request.POST.get('lastname'),
            'emailAddress': request.POST.get('email'),
            'mobileNumber': request.POST.get('mobile'),
            'location': request.POST.get('location'),
        }
        db.collection('users').document(user_id).update(updated_data)
        messages.success(request, 'User updated successfully')
    return render(request, 'register_user.html', {'users': user_list})


from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from math import ceil

def register_admin(request):
    """Register a new admin user"""
    # Check PIN verification
    if not request.session.get('auth_pin_verified'):
        return redirect(f'/admin/verify-auth-pin/?action=register')
    
    if request.method == 'POST':
        full_name = request.POST.get('fullName')
        email = request.POST.get('email')
        contact_number = request.POST.get('contactNumber')
        city = request.POST.get('city')
        password = request.POST.get('password')
        
        # Verify password
        if password != 'Sudo@123':
            messages.error(request, 'Invalid password. Default password is Sudo@123')
            return render(request, 'register_admin.html')
        
        try:
            db = firestore.client()
            ist = pytz.timezone('Asia/Kolkata')
            current_time = now().astimezone(ist)
            
            # Check if user already exists
            user_ref = db.collection('users').where(filter=FieldFilter('emailAddress', '==', email)).stream()
            existing_user = list(user_ref)
            if existing_user:
                messages.error(request, 'User with this email already exists.')
                return render(request, 'register_admin.html')
            
            # Generate user ID
            user_id = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8')[:28]
            
            # Create user data
            user_data = {
                'fullName': full_name,
                'emailAddress': email,
                'contactNumber': contact_number,
                'city': city,
                'roleId': 1,  # Admin role
                'createdAt': current_time,
                'enabled': True,
                'accountDeleted': False,
                'mustChangePassword': False,
                'enableIdCheck': False,
                'isOnline': False,
                'lastSeen': current_time,
                'id': user_id,
                'displayAddress': city,
                'formattedAddress': city,
                'street': '',
                'district': '',
                'latitude': 0,
                'longitude': 0,
                'profilePicture': '',
                'fcmToken': '',
                'fcmTokens': []
            }
            
            # Save to Firestore
            db.collection('users').document(user_id).set(user_data)
            
            messages.success(request, f'Admin user {full_name} registered successfully! You can now login.')
            # Clear PIN verification after successful registration
            request.session.pop('auth_pin_verified', None)
            return redirect('admin_login')
            
        except Exception as e:
            messages.error(request, f'Error registering admin: {str(e)}')
    
    return render(request, 'register_admin.html')

def manage_users(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')

    db = firestore.client()
    ADMIN_EMAIL = "sudotagonline@gmail.com"
    
    try:
        users_ref = db.collection('users')
        docs = users_ref.stream()
        
        users = []
        for doc in docs:
            user_data = doc.to_dict() or {}
            if user_data.get('emailAddress') == ADMIN_EMAIL:
                continue
                
            user_data['doc_id'] = doc.id
            users.append(user_data)
            
        if not users:
            messages.info(request, 'No users found in database')

    except Exception as e:
        messages.error(request, f'Error accessing database: {str(e)}')
        users = []

    # Pagination
    page = request.GET.get('page', 1)
    items_per_page = 10  # You can adjust this number
    
    paginator = Paginator(users, items_per_page)
    
    try:
        users_page = paginator.page(page)
    except PageNotAnInteger:
        users_page = paginator.page(1)
    except EmptyPage:
        users_page = paginator.page(paginator.num_pages)

    if request.method == "POST":
        if 'delete_selected' in request.POST:
            return handle_bulk_delete(request, users_ref)
        elif 'delete_single' in request.POST:
            user_id = request.POST.get('user_id')
            user_doc = users_ref.document(user_id).get()
            if user_doc.exists and user_doc.to_dict().get('emailAddress') == ADMIN_EMAIL:
                messages.error(request, 'Cannot delete admin account')
                return redirect('manage_users')
            return handle_single_delete(request, users_ref)
        # Removed toggle_status feature - users can only view details now
        elif 'update_user' in request.POST:
            user_id = request.POST.get('user_id')
            users_ref.document(user_id).update({
                'fullName': request.POST.get('fullName'),
                'city': request.POST.get('city')
            })
            messages.success(request, 'User updated successfully')
            return redirect('manage_users')

    return render(request, 'manage_users.html', {
        'users': users_page,
        'paginator': paginator,
        'messages': get_message_list(request)
    })

def handle_bulk_delete(request, users_ref):
    selected_user_ids = request.POST.getlist('selected_users')
    
    if not selected_user_ids:
        messages.warning(request, 'No users selected for deletion')
        return redirect('manage_users')
    
    success_count = 0
    for user_id in selected_user_ids:
        try:
            users_ref.document(user_id).delete()
            success_count += 1
        except Exception as e:
            messages.error(request, f'Error deleting user {user_id}: {str(e)}')
    
    if success_count > 0:
        msg = f'Successfully deleted {success_count} user(s)'
        if success_count != len(selected_user_ids):
            msg += f' (failed to delete {len(selected_user_ids) - success_count})'
        messages.success(request, msg)
    else:
        messages.error(request, 'Failed to delete all selected users')
    
    return redirect('manage_users')


def handle_single_delete(request, users_ref):
    user_id = request.POST.get('user_id')
    
    if not user_id:
        messages.warning(request, 'No user selected for deletion')
        return redirect('manage_users')
    
    try:
        users_ref.document(user_id).delete()
        messages.success(request, 'User deleted successfully')
    except Exception as e:
        messages.error(request, f'Error deleting user: {str(e)}')
    
    return redirect('manage_users')


def get_message_list(request):
    return [{
        'text': str(message.message) if hasattr(message, 'message') else str(message),
        'class': message.tags or 'info'
    } for message in messages.get_messages(request)]


def generate_random_password():
    """
    Generate a password that matches the mobile app validation pattern:
    Example: Aslam@1234 (1 uppercase, 4 lowercase, '@', 4 digits)
    """
    uppercase_letter = secrets.choice(string.ascii_uppercase)
    lowercase_segment = ''.join(secrets.choice(string.ascii_lowercase) for _ in range(4))
    numeric_segment = ''.join(secrets.choice(string.digits) for _ in range(4))

    return f"{uppercase_letter}{lowercase_segment}@{numeric_segment}"

def check_id_enabled(request, qr_id):
    try:
        # Check if QR code exists and is assigned
        qr_ref = db.collection('qrcodes').document(qr_id)
        qr_doc = qr_ref.get()
        
        if not qr_doc.exists:
            return render(request, 'invalid_qr.html', {'error': 'Invalid QR Code'})
        
        qr_data = qr_doc.to_dict()
        
        if qr_data.get('isAssigned', False):
            # Get the associated vehicle
            vehicle_ref = db.collection('vehicles').document(qr_data['vehicleID'])
            vehicle_doc = vehicle_ref.get()
            
            if vehicle_doc.exists:
                vehicle_data = vehicle_doc.to_dict()
                # Get the user data
                user_ref = db.collection('users').document(vehicle_data['ownerId'])
                user_doc = user_ref.get()
                
                if user_doc.exists and user_doc.to_dict().get('enableIdCheck', False):
                    return redirect('send_notification', qr_id=qr_id)
            
        # If QR not assigned or user not enabled, redirect to activation
        return redirect('activate_id', qr_id=qr_id)
            
    except Exception as e:
        return render(request, 'error.html', {'error': str(e)})

def send_welcome_email_for_id(email, name, password):
    subject = 'Welcome to Sudo - Your Account is Ready!'
    
    html_message = render_to_string('welcome_email_register.html', {
        'name': name,
        'email': email,
        'password': password,
        'login_url': 'https://play.google.com/',
        'support_email': 'support@sudo.com'
    })
    
    plain_message = f"""
    Welcome to Sudo, {name}!
    
    Your account has been successfully created. Here are your login details:
    
    Email: {email}
    Password: {password}
    
    Please login at: https://play.google.com
    
    We recommend changing your password after first login.
    
    If you have any questions, please contact our support team at support@sudo.com.
    
    Thank you,
    The Sudo Team
    """
    
    send_mail(
        subject=subject,
        message=plain_message,
        html_message=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False
    )

def send_vehicle_registration_email(email, name, vehicle_data):
    subject = 'Your Vehicle Registration is Complete!'
    
    html_message = render_to_string('vehicle_registration.html', {
        'name': name,
        'email': email,
        'make': vehicle_data['make'],
        'model': vehicle_data['model'],
        'registrationNumber': vehicle_data['registrationNumber'],
        'vehicleType': vehicle_data['vehicleType'],
        'support_email': 'support@sudo.com'
    })
    
    plain_message = f"""
    Hello {name},
    
    Your vehicle has been successfully registered with Sudo:
    
    Make: {vehicle_data['make']}
    Model: {vehicle_data['model']}
    Registration: {vehicle_data['registrationNumber']}
    Type: {vehicle_data['vehicleType']}
    
    Your QR code is now active and can be scanned by others to contact you about your vehicle.
    
    If you have any questions, please contact our support team at support@sudo.com.
    
    Thank you,
    The Sudo Team
    """
    
    send_mail(
        subject=subject,
        message=plain_message,
        html_message=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False
    )

@ensure_csrf_cookie
def activate_id(request, qr_id):
    try:
        # Verify QR code exists first
        qr_ref = db.collection('qrcodes').document(qr_id)
        qr_doc = qr_ref.get()
        
        if not qr_doc.exists:
            return render(request, 'invalid_qr.html', {'error': 'Invalid QR Code'})
        
        qr_data = qr_doc.to_dict()
        
        if qr_data.get('isAssigned', False):
            return redirect('send_notification', qr_id=qr_id)
        
        if request.method == 'POST':
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                import json
                data = json.loads(request.body)
                admin_added_user = str(data.get('adminAddedUser', 'false')).lower() == 'true'
                
                # Validate required fields
                required_fields = {
                    'user': ['fullName', 'contactNumber', 'city', 'emailAddress'],
                    'vehicle': ['make', 'model', 'registrationNumber', 'vehicleType']
                }
                
                errors = {}
                for field in required_fields['user']:
                    if not data.get(field):
                        errors[field] = 'This field is required'
                
                for field in required_fields['vehicle']:
                    if not data.get(field):
                        errors[field] = 'This field is required'
                
                # Validate email format
                if data.get('emailAddress'):
                    from django.core.validators import validate_email
                    from django.core.exceptions import ValidationError
                    try:
                        validate_email(data['emailAddress'])
                    except ValidationError:
                        errors['emailAddress'] = 'Enter a valid email address'
                
                if errors:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Please correct the errors',
                        'errors': errors
                    }, status=400)
                
                try:
                    # Check if user exists in Firestore
                    user_query = db.collection('users').where(filter=FieldFilter('emailAddress', '==', data['emailAddress'])).limit(1).get()
                    user_exists_in_firestore = len(user_query) > 0
                    
                    # Check if user exists in Firebase Auth (try to get user)
                    try:
                        auth_user = auth.get_user_by_email(data['emailAddress'])
                        user_exists_in_auth = True
                    except:
                        user_exists_in_auth = False
                    
                    # Handle different cases
                    if user_exists_in_auth and user_exists_in_firestore:
                        # Existing user - proceed with vehicle registration
                        user_doc = user_query[0]
                        user_data = user_doc.to_dict()
                        user_id = user_doc.id
                        if admin_added_user:
                            db.collection('users').document(user_id).update({'adminAddedUser': True})
                        else:
                            db.collection('users').document(user_id).update({'adminAddedUser': False})
                        
                        # Verify phone matches existing user
                        if user_data.get('contactNumber', '').replace(' ', '') != data['contactNumber'].replace(' ', ''):
                            return JsonResponse({
                                'status': 'error',
                                'message': 'Phone number does not match existing account',
                                'errors': {'contactNumber': 'This phone number does not match your existing account'}
                            }, status=400)

                            
                    elif user_exists_in_auth and not user_exists_in_firestore:
                        # Edge case: user in auth but not in firestore - shouldn't happen
                        return JsonResponse({
                            'status': 'error',
                            'message': 'Account exists but data is incomplete. Please contact support.',
                            'errors': {'emailAddress': 'Account issue detected'}
                        }, status=400)
                        
                    elif not user_exists_in_auth and user_exists_in_firestore:
                        # Edge case: user in firestore but not auth - shouldn't happen
                        return JsonResponse({
                            'status': 'error',
                            'message': 'Account data mismatch. Please contact support.',
                            'errors': {'emailAddress': 'Account issue detected'}
                        }, status=400)
                        
                    else:
                        # New user - create account
                        password = generate_random_password()
                        
                        try:
                            user = auth.create_user(
                                email=data['emailAddress'],
                                email_verified=False,
                                password=password,
                                display_name=data['fullName'],
                                disabled=False
                            )
                        except auth.EmailAlreadyExistsError:
                            # Handle case where user was created between our check and creation attempt
                            user = auth.get_user_by_email(data['emailAddress'])
                            
                        # Create user data in Firestore
                        user_data = {
                            'uid': user.uid,
                            'fullName': data.get('fullName'),
                            'contactNumber': data.get('contactNumber'),
                            'city': data.get('city'),
                            'emailAddress': data.get('emailAddress'),
                            'enableIdCheck': True,
                            'createdAt': firestore.SERVER_TIMESTAMP,
                            'profilePicture': 'default_profile.png',
                            'role': 0,
                            'roleId': 0,
                            'fcmToken': '',
                            'adminAddedUser': admin_added_user
                        }
                        
                        user_ref = db.collection('users').document(user.uid)
                        user_ref.set(user_data)
                        user_id = user.uid
                        if admin_added_user:
                            user_ref.update({'adminAddedUser': True})
                        
                        # Send welcome email only for new users
                        send_welcome_email_for_id(
                            email=data['emailAddress'],
                            name=data['fullName'],
                            password=password
                        )
                    
                    # Check if this vehicle is already registered to this user
                    vehicle_query = db.collection('vehicles').where(filter=FieldFilter('ownerId', '==', user_id))\
                        .where(filter=FieldFilter('registrationNumber', '==', data['registrationNumber'])).limit(1).get()
                    
                    if len(vehicle_query) > 0:
                        return JsonResponse({
                            'status': 'error',
                            'message': 'This vehicle is already registered to your account',
                            'errors': {'registrationNumber': 'This vehicle is already registered'}
                        }, status=400)
                    
                    # Create vehicle document (for both new and existing users)
                    vehicle_id = str(uuid.uuid4())
                    vehicle_data = {
                        'ownerId': user_id,
                        'ownerFullName': data.get('fullName'),
                        'ownerContact': data.get('contactNumber'),
                        'make': data.get('make'),
                        'model': data.get('model'),
                        'registrationNumber': data.get('registrationNumber'),
                        'vehicleType': data.get('vehicleType'),
                        'createdAt': firestore.SERVER_TIMESTAMP,
                        'isQrGenerated': True,
                        'qrCodeId': qr_id,
                        'adminAddedUser': admin_added_user
                    }
                    
                    vehicle_ref = db.collection('vehicles').document(vehicle_id)
                    vehicle_ref.set(vehicle_data)
                    
                    # Update QR code to mark as assigned
                    qr_ref.update({
                        'isAssigned': True,
                        'vehicleID': vehicle_id,
                        'userID': user_id,
                        'assignedAt': firestore.SERVER_TIMESTAMP
                    })
                    
                    # Send vehicle registration email
                    send_vehicle_registration_email(
                        email=data['emailAddress'],
                        name=data['fullName'],
                        vehicle_data=vehicle_data
                    )
                    
                    return JsonResponse({
                        'status': 'success', 
                        'message': 'Vehicle registration completed successfully!',
                        'redirect_url': reverse('send_notification', args=[qr_id]),
                        'is_new_user': not user_exists_in_auth
                    })
                    
                except Exception as e:
                    # Clean up Firebase Auth user if creation failed
                    if 'user' in locals() and user and not user_exists_in_auth:
                        try:
                            auth.delete_user(user.uid)
                        except:
                            pass
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Registration failed: {str(e)}'
                    }, status=500)
        
        # Render the registration form
        context = {
            'is_new_registration': True
        }
        
        return render(request, 'activate_id.html', context)
    
    except Exception as e:
        return render(request, 'error.html', {'error': str(e)})

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from firebase_admin import firestore, messaging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


# Rate limiting constants
DAILY_CALL_LIMIT = 2
DAILY_SMS_LIMIT = 2


def get_today_date_string():
    """Return today's date string in Asia/Kolkata timezone (YYYY-MM-DD)."""
    ist = pytz.timezone('Asia/Kolkata')
    return now().astimezone(ist).strftime('%Y-%m-%d')


def check_daily_limit(qr_id, action_type):
    """Check whether the daily limit has been reached for the given action."""
    try:
        # Push notifications remain unlimited
        if action_type == 'push':
            return True, 0, None

        today = get_today_date_string()
        usage_ref = db.collection('daily_usage').document(f"{qr_id}_{today}")
        usage_doc = usage_ref.get()

        if action_type == 'call':
            limit = DAILY_CALL_LIMIT
            count_field = 'calls_count'
        elif action_type == 'sms':
            limit = DAILY_SMS_LIMIT
            count_field = 'sms_count'
        else:
            return True, 0, None

        if not usage_doc.exists:
            return True, 0, limit

        usage_data = usage_doc.to_dict() or {}
        current_count = usage_data.get(count_field, 0) or 0

        try:
            current_count = int(current_count)
        except (TypeError, ValueError):
            logger.warning(
                "daily_usage document %s has non-integer %s=%r; resetting to 0",
                usage_ref.id,
                count_field,
                current_count,
            )
            current_count = 0
            usage_ref.update({count_field: 0})

        return current_count < limit, current_count, limit

    except Exception as exc:
        logger.error(f"Error checking daily limit: {exc}")
        # Fail open so users are not blocked due to Firestore issues
        if action_type == 'call':
            limit = DAILY_CALL_LIMIT
        elif action_type == 'sms':
            limit = DAILY_SMS_LIMIT
        else:
            limit = None
        return True, 0, limit


def increment_daily_count(qr_id, action_type):
    """Increment the stored daily count for the provided action."""
    try:
        if action_type == 'push':
            return

        today = get_today_date_string()
        usage_ref = db.collection('daily_usage').document(f"{qr_id}_{today}")

        if action_type == 'call':
            count_field = 'calls_count'
        elif action_type == 'sms':
            count_field = 'sms_count'
        else:
            return

        # Ensure the document exists and has the basic metadata.
        usage_ref.set({
            'qr_id': qr_id,
            'date': today,
        }, merge=True)

        usage_ref.update({
            count_field: firestore.Increment(1),
            'last_updated': firestore.SERVER_TIMESTAMP,
        })

    except Exception as exc:
        logger.error(f"Error incrementing daily count: {exc}")

def get_twilio_error_message(twilio_exception):
    """
    Convert Twilio error codes to user-friendly messages
    """
    error_messages = {
        20003: "Authentication failed. Please check Twilio credentials.",
        21211: "Invalid phone number format. Please use format: +1234567890",
        21408: "Permission denied. This feature is not enabled.",
        21610: "Phone number is not verified. Please verify your number.",
        30007: "Delivery failed. The destination number cannot receive messages.",
        14101: "Invalid To phone number. Please check the number format.",
        13225: "Max price parameter is invalid.",
        13224: "Message delivery failed.",
        21612: "Cannot send SMS to this country.",
        21614: "This phone number is not currently reachable.",
        21217: "Phone number is too short.",
        21216: "Phone number is too long.",
        21215: "Invalid phone number.",
        14103: "Call cannot be completed.",
        13227: "Phone number is blacklisted.",
    }
    
    return error_messages.get(twilio_exception.code, f"Twilio error: {twilio_exception.msg}")

@ensure_csrf_cookie
def send_notification(request, qr_id):
    try:
        # Get QR code data
        qr_ref = db.collection('qrcodes').document(qr_id)
        qr_doc = qr_ref.get()

        if not qr_doc.exists or not qr_doc.to_dict().get('isAssigned', False):
            return render(request, 'error.html', {'error': 'QR code not assigned!'})

        qr_data = qr_doc.to_dict()
        
        # Get vehicle data
        vehicle_ref = db.collection('vehicles').document(qr_data['vehicleID'])
        vehicle_doc = vehicle_ref.get()
        
        if not vehicle_doc.exists:
            return render(request, 'error.html', {'error': 'Vehicle not found!'})

        vehicle_data = vehicle_doc.to_dict()
        
        # Get user data
        user_ref = db.collection('users').document(vehicle_data['ownerId'])
        user_doc = user_ref.get()
        
        if not user_doc.exists or not user_doc.to_dict().get('enableIdCheck', False):
            return redirect('activate_id', qr_id=qr_id)
        
        user_data = user_doc.to_dict()
        
        if request.method == 'POST':
            # Handle AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                import json
                data = json.loads(request.body)
                
                reason = data.get('reason')
                plate_digits = data.get('plate_digits')
                user_phone = data.get('user_phone', '')
                notification_method = data.get('notification_method', 'push')
                
                # Handle different notification methods
                if notification_method == 'push':
                    # Existing push notification code
                    fcm_token = user_data.get('fcmToken')
                    
                    if not fcm_token:
                        return JsonResponse({
                            'status': 'error', 
                            'message': 'User is not registered on app.'
                        })

                    message = messaging.Message(
                        notification=messaging.Notification(
                            title="Vehicle Alert",
                            body=reason,
                        ),
                        token=fcm_token,
                        data={
                            'vehicleId': qr_data['vehicleID'],
                            'qrId': qr_id,
                            'notificationType': 'vehicle_alert'
                        }
                    )

                    try:
                        response = messaging.send(message)
                        return JsonResponse({
                            'status': 'success', 
                            'message': 'We have sent your message to the vehicle owner.'
                        })
                    except Exception as e:
                        logger.error(f"FCM Error: {str(e)}")
                        return JsonResponse({
                            'status': 'error', 
                            'message': f'Failed to send push notification: {str(e)}'
                        })
                
                elif notification_method in ['call', 'sms']:
                    try:
                        # Validate Twilio configuration
                        if not hasattr(settings, 'TWILIO_ACCOUNT_SID') or not settings.TWILIO_ACCOUNT_SID:
                            return JsonResponse({
                                'status': 'error',
                                'message': 'SMS/Call service is not configured. Please try push notification instead.'
                            })
                        
                        if not hasattr(settings, 'TWILIO_AUTH_TOKEN') or not settings.TWILIO_AUTH_TOKEN:
                            return JsonResponse({
                                'status': 'error',
                                'message': 'SMS/Call service is not configured. Please try push notification instead.'
                            })
                        
                        if not hasattr(settings, 'TWILIO_PHONE_NUMBER') or not settings.TWILIO_PHONE_NUMBER:
                            return JsonResponse({
                                'status': 'error',
                                'message': 'SMS/Call service is not configured. Please try push notification instead.'
                            })

                        # Initialize Twilio client
                        twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                        owner_phone = user_data.get('contactNumber', '')
                        
                        if not owner_phone:
                            return JsonResponse({
                                'status': 'error',
                                'message': 'Owner does not have a valid phone number registered.'
                            })
                        
                        # Validate phone number format
                        if not owner_phone.startswith('+'):
                            return JsonResponse({
                                'status': 'error',
                                'message': 'Owner phone number must include country code (e.g., +91 for India).'
                            })

                        if notification_method == 'sms':
                            is_allowed, current_count, limit = check_daily_limit(qr_id, 'sms')

                            if not is_allowed:
                                return JsonResponse({
                                    'status': 'error',
                                    'error_type': 'daily_limit_reached',
                                    'message': f'Daily SMS limit reached. You have used {current_count} out of {limit} SMS messages today. Please try again tomorrow.',
                                    'current_count': current_count,
                                    'limit': limit,
                                })

                            message = twilio_client.messages.create(
                                body=f"Vehicle Alert: {reason}\n\nFrom: {user_phone or 'Anonymous'}",
                                from_=settings.TWILIO_PHONE_NUMBER,
                                to=owner_phone
                            )
                            logger.info(f"SMS sent successfully: {message.sid}")
                            increment_daily_count(qr_id, 'sms')
                            return JsonResponse({
                                'status': 'success',
                                'message': 'SMS sent successfully to the vehicle owner.'
                            })
                        
                        elif notification_method == 'call':
                            is_allowed, current_count, limit = check_daily_limit(qr_id, 'call')

                            if not is_allowed:
                                return JsonResponse({
                                    'status': 'error',
                                    'error_type': 'daily_limit_reached',
                                    'message': f'Daily call limit reached. You have used {current_count} out of {limit} calls today. Please try again tomorrow.',
                                    'current_count': current_count,
                                    'limit': limit,
                                })

                            call = twilio_client.calls.create(
                                twiml=f'<Response><Say>Hello, this is an important message about your vehicle. {reason}. The person trying to reach you provided this number: {user_phone or "not provided"}. Thank you from Sudo.</Say></Response>',
                                from_=settings.TWILIO_PHONE_NUMBER,
                                to=owner_phone
                            )
                            logger.info(f"Call initiated successfully: {call.sid}")
                            increment_daily_count(qr_id, 'call')
                            return JsonResponse({
                                'status': 'success',
                                'message': 'Phone call initiated successfully to the vehicle owner.'
                            })
                    
                    except TwilioRestException as e:
                        logger.error(f"Twilio Error {e.code}: {e.msg}")
                        user_message = get_twilio_error_message(e)
                        
                        # Special handling for common errors
                        if e.code == 20003:
                            user_message = "SMS/Call service is temporarily unavailable. Please try push notification instead."
                        elif e.code == 21211:
                            user_message = "Invalid phone number format. The owner's phone number needs to include country code."
                        elif e.code in [21408, 21610]:
                            user_message = "SMS/Call feature is not available for this number. Please try push notification."
                        elif e.code == 30007:
                            user_message = "Unable to deliver message to the owner's phone number. It may be inactive or blocked."
                        
                        return JsonResponse({
                            'status': 'error',
                            'message': user_message
                        })
                        
                    except Exception as e:
                        logger.error(f"Unexpected Twilio error: {str(e)}")
                        return JsonResponse({
                            'status': 'error',
                            'message': f'Failed to send {notification_method}. Please try again or use push notification.'
                        })

        # Render the initial page with vehicle data
        context = {
            'vehicle_data': {
                'model': vehicle_data.get('model', ''),
                'registrationNumber': vehicle_data.get('registrationNumber', '')
            }
        }
        
        return render(request, 'send_notification.html', context)
    
    except Exception as e:
        logger.error(f"General error in send_notification: {str(e)}")
        return render(request, 'error.html', {'error': str(e)})
    
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import json
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

# Define status mapping
STATUS_MAPPING = {
    0: "Pending",
    1: "Processing",
    2: "Shipped",
    3: "Delivered",
    4: "Cancelled",
    5: "Returned",
    6: "Failed",
    7: "On Hold",
}

def view_orders(request):
    try:
        # OPTIMIZED: Use query with limit and ordering for faster loading
        orders_ref = db.collection('orders')
        
        # Get pagination info
        page = request.GET.get('page', 1)
        items_per_page = 20  # Increased from 15
        
        # OPTIMIZED: Limit query results and use ordering
        # For better performance, limit to 1000 orders max
        try:
            # Try to use ordered query
            orders_query = orders_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1000)
            orders = orders_query.stream()
        except:
            # Fallback if ordering fails
            orders = orders_ref.limit(1000).stream()

        orders_data = []
        for order in orders:
            order_dict = order.to_dict()
            order_dict['id'] = order.id  # Add the document ID to the order data
            
            # Map order status to its corresponding text
            order_status = order_dict.get('orderStatus', 0)
            order_dict['status_text'] = STATUS_MAPPING.get(order_status, "Unknown")

            orders_data.append({
                'order': order_dict,
            })

        # Sort by timestamp (newest first) if not already sorted
        if orders_data:
            orders_data.sort(key=lambda x: x['order'].get('timestamp', ''), reverse=True)

        # Pagination
        
        paginator = Paginator(orders_data, items_per_page)
        
        try:
            orders_page = paginator.page(page)
        except PageNotAnInteger:
            orders_page = paginator.page(1)
        except EmptyPage:
            orders_page = paginator.page(paginator.num_pages)

        context = {
            'orders': orders_page,
            'paginator': paginator,
            'STATUS_MAPPING': STATUS_MAPPING,
        }
        return render(request, 'view_orders.html', context)

    except Exception as e:
        return render(request, 'view_orders.html', {'error': str(e)})

def view_payments(request):
    """View all payments from the payments collection"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    try:
        payments_ref = db.collection('payments')
        
        # Get pagination info
        page = request.GET.get('page', 1)
        items_per_page = 20
        
        # Get all payments
        payments_docs = list(payments_ref.limit(1000).stream())
        
        payments_data = []
        for doc in payments_docs:
            payment_dict = doc.to_dict()
            payment_dict['id'] = doc.id
            payments_data.append({
                'payment': payment_dict,
            })
        
        # Sort by timestamp (newest first)
        payments_data.sort(key=lambda x: x['payment'].get('timestamp', ''), reverse=True)
        
        # Pagination
        paginator = Paginator(payments_data, items_per_page)
        
        try:
            payments_page = paginator.page(page)
        except PageNotAnInteger:
            payments_page = paginator.page(1)
        except EmptyPage:
            payments_page = paginator.page(paginator.num_pages)
        
        return render(request, 'view_payments.html', {
            'payments': payments_page,
            'paginator': paginator,
        })
    except Exception as e:
        messages.error(request, f'Error loading payments: {str(e)}')
        return render(request, 'view_payments.html', {
            'payments': [],
            'paginator': None,
        })

@csrf_exempt
def update_order_status(request):
    if request.method == 'POST':
        try:
            # Get the raw POST data
            if request.body:
                try:
                    data = json.loads(request.body)
                    order_id = data.get('orderId')
                    new_status = int(data.get('newStatus'))
                except json.JSONDecodeError:
                    # Fallback to form data
                    order_id = request.POST.get('orderId')
                    new_status = int(request.POST.get('newStatus', 0))
            else:
                order_id = request.POST.get('orderId')
                new_status = int(request.POST.get('newStatus', 0))

            if not order_id:
                return JsonResponse({'success': False, 'error': 'Order ID is required'})

            print(f"Updating order {order_id} to status {new_status}")  # Debug

            # Update ONLY the order status in the database
            order_ref = db.collection('orders').document(order_id)
            order_ref.update({
                'orderStatus': new_status,
            })

            return JsonResponse({
                'success': True,
                'status_text': STATUS_MAPPING.get(new_status, "Unknown")
            })
            
        except Exception as e:
            print(f"Error in update_order_status: {str(e)}")  # Debug
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

# =========================
# Archiving (Deleted Users)
# =========================
from .models import ArchivedUser, ArchivedVehicle
from django.db import transaction
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import datetime as _dt
from django.http import HttpResponse
import csv


def _to_datetime_or_none(value):
    try:
        if hasattr(value, "to_datetime"):
            return value.to_datetime()
        if isinstance(value, (_dt.datetime, )):
            return value
        if hasattr(value, "strftime"):
            return value  # assume datetime-like
    except Exception:
        pass
    return None


def _safe_str(value, default=''):
    """Safely convert value to string, handling None."""
    if value is None:
        return default
    return str(value) if value else default


def _serialize_firestore_data(data):
    """
    Convert Firestore data to JSON-serializable format.
    Handles DatetimeWithNanoseconds and other Firestore types.
    """
    if data is None:
        return None
    
    # Handle Firestore datetime objects
    if hasattr(data, 'to_datetime'):
        try:
            dt = data.to_datetime()
            return dt.isoformat() if dt else None
        except:
            return str(data)
    
    # Handle Python datetime objects
    if isinstance(data, _dt.datetime):
        return data.isoformat()
    
    # Handle dictionaries (recursive)
    if isinstance(data, dict):
        return {k: _serialize_firestore_data(v) for k, v in data.items()}
    
    # Handle lists (recursive)
    if isinstance(data, list):
        return [_serialize_firestore_data(item) for item in data]
    
    # Handle other types that might not be JSON serializable
    try:
        import json
        json.dumps(data)  # Test if serializable
        return data
    except (TypeError, ValueError):
        return str(data)  # Fallback to string representation


@csrf_exempt
def archive_deleted_user_webhook(request):
    """
    Receive a webhook when a user deletes the account from the mobile app.
    
    User ID can be provided in two ways:
    1. URL parameter: ?user_id=<USER_ID> (easiest for testing)
    2. JSON body: { "user_id": "<USER_ID>" }
    
    Auth: header X-Webhook-Token must equal settings.DELETION_WEBHOOK_SECRET (if set).
    Or use query parameter: ?token=<SECRET>
    
    Example URLs:
    - /admin/api/archive-deleted-user/?user_id=ABC123&token=1234567890
    - /admin/api/archive-deleted-user/ (with JSON body and header)
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

    # Simple shared-secret validation (optional if secret is unset)
    expected = getattr(settings, 'DELETION_WEBHOOK_SECRET', '') or ''
    
    # Try multiple ways to get the token (Django converts headers to HTTP_X_WEBHOOK_TOKEN)
    provided = (
        request.headers.get('X-Webhook-Token') or 
        request.headers.get('x-webhook-token') or
        request.META.get('HTTP_X_WEBHOOK_TOKEN') or
        request.GET.get('token') or 
        ''
    )
    
    if expected:
        if not provided:
            return JsonResponse({
                'status': 'error', 
                'message': 'Unauthorized: Missing X-Webhook-Token header or token parameter'
            }, status=401)
        if provided != expected:
            return JsonResponse({
                'status': 'error', 
                'message': 'Unauthorized: Invalid token'
            }, status=401)

    # Get user_id from URL parameter (for easy testing) or JSON body
    user_id = request.GET.get('user_id') or request.GET.get('uid') or request.GET.get('userId')
    
    # If not in URL, try JSON body
    if not user_id:
        try:
            data = json.loads(request.body or '{}')
            user_id = data.get('user_id') or data.get('uid') or data.get('userId')
        except json.JSONDecodeError:
            # If JSON is invalid but we have URL param, that's okay
            pass
    
    if not user_id:
        return JsonResponse({
            'status': 'error', 
            'message': 'Missing user_id. Provide it as URL parameter (?user_id=...) or in JSON body.'
        }, status=400)

    try:
        # Fetch user and vehicles from Firestore
        user_doc = db.collection('users').document(user_id).get()
        user_dict = user_doc.to_dict() if user_doc.exists else {}

        vehicles_stream = db.collection('vehicles').where(filter=FieldFilter('ownerId', '==', user_id)).stream()
        vehicles = []
        for vdoc in vehicles_stream:
            v = vdoc.to_dict() or {}
            v['_doc_id'] = vdoc.id
            vehicles.append(v)

        # Archive into SQLite
        with transaction.atomic():
            # Always archive user (even if user_dict is empty, we still want to record the deletion)
            user_dict = user_dict or {}  # Ensure it's never None
            serialized_user = _serialize_firestore_data(user_dict)
            
            ArchivedUser.objects.update_or_create(
                user_id=user_id,
                defaults={
                    'email': _safe_str(user_dict.get('emailAddress'), ''),
                    'full_name': _safe_str(user_dict.get('fullName'), ''),
                    'phone': _safe_str(user_dict.get('contactNumber'), ''),
                    'original_created_at': _to_datetime_or_none(user_dict.get('createdAt')),
                    'raw': serialized_user or {},
                }
            )

            saved_vehicle_count = 0
            for v in vehicles:
                # Serialize Firestore data to JSON-serializable format
                serialized_vehicle = _serialize_firestore_data(v)
                
                # Get vehicle_id safely
                vehicle_id = _safe_str(v.get('_doc_id') or v.get('vehicleId'), '')
                if not vehicle_id:
                    vehicle_id = f"unknown_{saved_vehicle_count}"  # Fallback ID
                
                ArchivedVehicle.objects.update_or_create(
                    vehicle_id=vehicle_id,
                    defaults={
                        'owner_id': user_id,
                        'registration_number': _safe_str(v.get('registrationNumber'), ''),
                        'make': _safe_str(v.get('make'), ''),
                        'model': _safe_str(v.get('model'), ''),
                        'vehicle_type': _safe_str(v.get('vehicleType'), ''),
                        'owner_contact': _safe_str(v.get('ownerContact'), ''),
                        'qr_code_id': _safe_str(v.get('qrCodeId') or v.get('qrId'), ''),
                        'original_created_at': _to_datetime_or_none(v.get('createdAt')),
                        'raw': serialized_vehicle or {},
                    }
                )
                saved_vehicle_count += 1

        return JsonResponse({
            'status': 'success',
            'archived_user': True,  # Always true since we always archive
            'archived_vehicle_count': saved_vehicle_count,
        })

    except Exception as e:
        logger.error(f"Archive webhook error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def _paginate_queryset(request, qs, per_page=20):
    paginator = Paginator(qs, per_page)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return page_obj, paginator


def view_archived_data(request):
    """
    Unified view showing archived users with their vehicles together.
    Each user row shows their details, and below it lists all their vehicles.
    """
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')

    q = request.GET.get('q', '').strip()
    users = ArchivedUser.objects.all().order_by('-archived_at')
    
    if q:
        # First, get all users matching regular fields
        regular_matches = users.filter(
            Q(user_id__icontains=q) |
            Q(full_name__icontains=q) |
            Q(email__icontains=q) |
            Q(phone__icontains=q)
        )
        
        # Also search in raw JSON field for city/location
        # Since raw is a JSONField, we need to filter in Python for city search
        q_lower = q.lower()
        city_match_ids = []
        all_users_list = list(ArchivedUser.objects.all())
        
        for user in all_users_list:
            raw_data = user.raw or {}
            city = raw_data.get('city', '')
            district = raw_data.get('district', '')
            display_address = raw_data.get('displayAddress', '')
            
            # Check if search term matches city, district, or address
            if (q_lower in city.lower() or 
                q_lower in district.lower() or 
                q_lower in display_address.lower()):
                city_match_ids.append(user.id)
        
        # Combine both sets of matches
        if city_match_ids:
            city_qs = ArchivedUser.objects.filter(id__in=city_match_ids)
            users = (regular_matches | city_qs).distinct().order_by('-archived_at')
        else:
            users = regular_matches
    
    # For each user, fetch their vehicles
    user_data = []
    for user in users:
        vehicles = ArchivedVehicle.objects.filter(owner_id=user.user_id).order_by('-archived_at')
        user_data.append({
            'user': user,
            'vehicles': list(vehicles),
            'vehicle_count': vehicles.count(),
        })
    
    # Pagination for list (not queryset)
    paginator = Paginator(user_data, per_page=10)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    return render(request, 'archived_data.html', {
        'user_data': page_obj,
        'paginator': paginator,
        'query': q,
        'total_users': ArchivedUser.objects.count(),
        'total_vehicles': ArchivedVehicle.objects.count(),
    })


def export_archived_data_csv(request):
    """
    Export all archived users and their vehicles in a single CSV file.
    Each row represents a user-vehicle combination (one row per vehicle per user).
    """
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    q = request.GET.get('q', '').strip()
    users = ArchivedUser.objects.all().order_by('-archived_at')
    
    if q:
        # First, get all users matching regular fields
        regular_matches = users.filter(
            Q(user_id__icontains=q) |
            Q(full_name__icontains=q) |
            Q(email__icontains=q) |
            Q(phone__icontains=q)
        )
        
        # Also search in raw JSON field for city/location
        q_lower = q.lower()
        city_match_ids = []
        all_users_list = list(ArchivedUser.objects.all())
        
        for user in all_users_list:
            raw_data = user.raw or {}
            city = raw_data.get('city', '')
            district = raw_data.get('district', '')
            display_address = raw_data.get('displayAddress', '')
            
            # Check if search term matches city, district, or address
            if (q_lower in city.lower() or 
                q_lower in district.lower() or 
                q_lower in display_address.lower()):
                city_match_ids.append(user.id)
        
        # Combine both sets of matches
        if city_match_ids:
            city_qs = ArchivedUser.objects.filter(id__in=city_match_ids)
            users = (regular_matches | city_qs).distinct().order_by('-archived_at')
        else:
            users = regular_matches
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="archived_users_and_vehicles.csv"'
    writer = csv.writer(response)
    
    # Header row with both user and vehicle columns
    writer.writerow([
        'User ID', 'User Full Name', 'User Email', 'User Phone', 'User Created At', 'User Archived At',
        'Vehicle ID', 'Vehicle Registration', 'Vehicle Make', 'Vehicle Model', 'Vehicle Type',
        'Owner Contact', 'QR Code ID', 'Vehicle Created At', 'Vehicle Archived At'
    ])
    
    # Write data: one row per vehicle (if user has no vehicles, write one row with user data only)
    for user in users:
        vehicles = ArchivedVehicle.objects.filter(owner_id=user.user_id).order_by('-archived_at')
        
        if vehicles.exists():
            # User has vehicles: write one row per vehicle
            for vehicle in vehicles:
                writer.writerow([
                    user.user_id,
                    user.full_name,
                    user.email,
                    user.phone,
                    user.original_created_at.isoformat() if user.original_created_at else '',
                    user.archived_at.isoformat() if user.archived_at else '',
                    vehicle.vehicle_id,
                    vehicle.registration_number,
                    vehicle.make,
                    vehicle.model,
                    vehicle.vehicle_type,
                    vehicle.owner_contact,
                    vehicle.qr_code_id,
                    vehicle.original_created_at.isoformat() if vehicle.original_created_at else '',
                    vehicle.archived_at.isoformat() if vehicle.archived_at else '',
                ])
        else:
            # User has no vehicles: write one row with user data only
            writer.writerow([
                user.user_id,
                user.full_name,
                user.email,
                user.phone,
                user.original_created_at.isoformat() if user.original_created_at else '',
                user.archived_at.isoformat() if user.archived_at else '',
                '',  # Vehicle ID
                '',  # Registration
                '',  # Make
                '',  # Model
                '',  # Type
                '',  # Owner Contact
                '',  # QR Code ID
                '',  # Vehicle Created At
                '',  # Vehicle Archived At
            ])
    
    return response


@csrf_exempt
def delete_archived_user(request, user_id):
    """Delete an archived user and all their vehicles"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
    
    try:
        user = ArchivedUser.objects.get(user_id=user_id)
        user_name = user.full_name or user.email or user_id
        
        # Delete all vehicles associated with this user
        vehicle_count = ArchivedVehicle.objects.filter(owner_id=user_id).delete()[0]
        
        # Delete the user
        user.delete()
        
        messages.success(request, f'Successfully deleted archived user "{user_name}" and {vehicle_count} vehicle(s).')
        return JsonResponse({
            'success': True,
            'message': f'Deleted user and {vehicle_count} vehicle(s)'
        })
    except ArchivedUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting archived user: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def delete_archived_vehicle(request, vehicle_id):
    """Delete an individual archived vehicle"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
    
    try:
        vehicle = ArchivedVehicle.objects.get(vehicle_id=vehicle_id)
        reg_number = vehicle.registration_number or vehicle_id
        vehicle.delete()
        
        messages.success(request, f'Successfully deleted archived vehicle "{reg_number}".')
        return JsonResponse({
            'success': True,
            'message': 'Vehicle deleted successfully'
        })
    except ArchivedVehicle.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Vehicle not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting archived vehicle: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def bulk_delete_archived(request):
    """Bulk delete archived users and/or vehicles"""
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body or '{}')
        user_ids = data.get('user_ids', [])
        vehicle_ids = data.get('vehicle_ids', [])
        
        deleted_users = 0
        deleted_vehicles = 0
        
        # Delete users (and their vehicles)
        if user_ids:
            for user_id in user_ids:
                try:
                    user = ArchivedUser.objects.get(user_id=user_id)
                    # Delete associated vehicles
                    ArchivedVehicle.objects.filter(owner_id=user_id).delete()
                    user.delete()
                    deleted_users += 1
                except ArchivedUser.DoesNotExist:
                    continue
        
        # Delete individual vehicles
        if vehicle_ids:
            deleted_vehicles = ArchivedVehicle.objects.filter(vehicle_id__in=vehicle_ids).delete()[0]
        
        message = f'Successfully deleted {deleted_users} user(s) and {deleted_vehicles} vehicle(s).'
        messages.success(request, message)
        
        return JsonResponse({
            'success': True,
            'deleted_users': deleted_users,
            'deleted_vehicles': deleted_vehicles,
            'message': message
        })
    except Exception as e:
        logger.error(f"Error in bulk delete: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# Keep old views for backward compatibility (redirect to unified view)
def view_archived_users(request):
    return redirect('view_archived_data')

def view_archived_vehicles(request):
    return redirect('view_archived_data')

def export_archived_users_csv(request):
    return redirect('export_archived_data_csv')

def export_archived_vehicles_csv(request):
    return redirect('export_archived_data_csv')
def external_user_registration(request):
    if request.method == 'POST':
        # Get form data
        full_name = request.POST.get('fullName')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        city = request.POST.get('city')
        
        # Generate user ID and random password
        user_id = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8')[:8]
        temp_password = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8')[:12]
        
        try:
            # Create Firebase Authentication user
            user = auth.create_user(
                email=email,
                email_verified=False,
                password=temp_password,
                display_name=full_name,
                disabled=False
            )
            
            # Create user data for Firestore
            user_data = {
                'userId': user_id,
                'fullName': full_name,
                'emailAddress': email,
                'contactNumber': phone,
                'city': city,
                'createdAt': datetime.datetime.now(),
                'role': 0,  # Regular user role
                'roleId': 0,
                'profilePicture': 'default_profile.png',
                'fcmToken': '',  # Will be set when user installs the app
                 'enableIdCheck': False,
                 'adminAddedUser': False
            }
            
            # Save to Firestore
            db.collection('users').document(user_id).set(user_data)
            
            # Send welcome email with credentials
            send_welcome_email(email, full_name, temp_password)
            
            # Success - redirect to thank you page
            return render(request, 'registration_success.html')
            
        except Exception as e:
            # Error handling
            return render(request, 'external_register.html', {
                'error': f'Registration failed: {str(e)}',
                'form_data': request.POST
            })
    
    # GET request - show empty form
    return render(request, 'external_register.html')

def send_welcome_email(email, name, password):
    subject = 'Welcome to Sudo - Your Account Details'
    
    # Render HTML email template
    html_message = render_to_string('welcome_email.html', {
        'name': name,
        'email': email,
        'password': password,
        'login_url': 'https://play.google.com/',
        'support_email': 'support@sudo.com'
    })
    
    # Plain text version
    plain_message = f"""
    Welcome to Sudo, {name}!
    
    Your account has been successfully created. Here are your login details:
    
    Email: {email}
    Temporary Password: {password}
    
    Please login at: https://play.google.com/
    
    We recommend changing your password after first login.
    
    If you have any questions, please contact our support team at support@sudo.com.
    
    Thank you,
    The Sudo Team
    """
    
    send_mail(
        subject=subject,
        message=plain_message,
        html_message=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False
    )


@csrf_exempt
def send_feedback(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Prepare email content
            context = {
                'name': data.get('name', 'User'),
                'email': data.get('email', ''),
                'vehicle': data.get('vehicle', ''),
                'rating': data.get('rating', 0),
                'feedback': data.get('feedback', 'No feedback provided'),
            }
            
            # Render email templates
            subject = f"New Feedback Received - Rating: {context['rating']}/5"
            text_content = render_to_string('feedback_email.txt', context)
            html_content = render_to_string('feedback_email.html', context)
            
            # Send email to admin
            send_mail(
                subject,
                text_content,
                settings.DEFAULT_FROM_EMAIL,
                [settings.FEEDBACK_EMAIL],
                html_message=html_content,
                fail_silently=False,
            )
            
            # Send confirmation to user
            if context['email']:
                user_subject = "Thank You for Your Feedback"
                user_text = render_to_string('feedback_user_email.txt', context)
                user_html = render_to_string('feedback_user_email.html', context)
                
                send_mail(
                    user_subject,
                    user_text,
                    settings.DEFAULT_FROM_EMAIL,
                    [context['email']],
                    html_message=user_html,
                    fail_silently=False,
                )
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def send_feedback_notify(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Prepare email content
            context = {
                'contact_reason': data.get('contact_reason', 'Not specified'),
                'feedback': data.get('feedback', 'No feedback provided'),
                'rating': data.get('rating', 0),
                'vehicle_model': data.get('vehicle_model', 'Unknown vehicle'),
                'notification_method': data.get('notification_method', 'push')
            }
            
            # Render email templates
            subject = f"New Feedback Received - Rating: {context['rating']}/5"
            text_content = render_to_string('feedback_email_notify.txt', context)
            html_content = render_to_string('feedback_email_notify.html', context)
            
            # Send email to admin
            send_mail(
                subject,
                text_content,
                settings.DEFAULT_FROM_EMAIL,
                [settings.FEEDBACK_EMAIL],
                html_message=html_content,
                fail_silently=False,
            )
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
import qrcode
import base64
from io import BytesIO

def manage_qrs(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')

    db = firestore.client()
    
    try:
        qrs_ref = db.collection('qrcodes')
        query = qrs_ref
        
        # Handle filters
        status_filter = request.GET.get('status')
        search_query = request.GET.get('search')
        
        if status_filter == 'active':
            query = query.where(filter=FieldFilter('isAssigned', '==', True))
        elif status_filter == 'inactive':
            query = query.where(filter=FieldFilter('isAssigned', '==', False))
        
        # OPTIMIZED: Limit query results to reduce loading time
        # Get pagination info first
        page = request.GET.get('page', 1)
        items_per_page = 20  # Increased from 10 for better UX
        
        # For now, we'll still need to load all for search, but limit processing
        # In production, consider implementing Firestore cursor-based pagination
        qr_docs = list(query.limit(500).stream())  # Limit to 500 max for performance
        
        # Prepare QR data with additional user/vehicle info
        qrs = []
        user_cache = {}
        vehicle_cache = {}
        
        for doc in qr_docs:
            qr_data = doc.to_dict() or {}
            qr_data['doc_id'] = doc.id
            
            # OPTIMIZED: Only generate QR code image if we'll display it (lazy loading)
            # We'll generate on-demand or cache it
            # For now, generate but cache the result
            try:
                qr = qrcode.QRCode(
                    version=3,
                    error_correction=qrcode.constants.ERROR_CORRECT_H,
                    box_size=4,
                    border=2,
                )
                qr.add_data(f"{settings.BASE_DOMAIN}/admin/send-notification/{doc.id}/")
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="#dcbd1f", back_color="#161416")
                
                # Convert to base64
                buffer = BytesIO()
                qr_img.save(buffer, format="PNG")
                qr_data['qr_code_base64'] = base64.b64encode(buffer.getvalue()).decode('utf-8')
            except Exception as e:
                qr_data['qr_code_base64'] = ''  # Skip if generation fails
            
            # Add user info if assigned
            if qr_data.get('isAssigned') and qr_data.get('userID'):
                if qr_data['userID'] not in user_cache:
                    try:
                        user_doc = db.collection('users').document(qr_data['userID']).get()
                        user_cache[qr_data['userID']] = user_doc.to_dict() if user_doc.exists else None
                    except:
                        user_cache[qr_data['userID']] = None
                
                qr_data['user'] = user_cache[qr_data['userID']]
            
            # Add vehicle info if assigned
            if qr_data.get('isAssigned') and qr_data.get('vehicleID'):
                if qr_data['vehicleID'] not in vehicle_cache:
                    try:
                        vehicle_doc = db.collection('vehicles').document(qr_data['vehicleID']).get()
                        vehicle_cache[qr_data['vehicleID']] = vehicle_doc.to_dict() if vehicle_doc.exists else None
                    except:
                        vehicle_cache[qr_data['vehicleID']] = None
                
                qr_data['vehicle'] = vehicle_cache[qr_data['vehicleID']]
            
            # Apply search filter if provided
            if search_query:
                search_lower = search_query.lower()
                matches = False
                
                # Check QR ID
                if search_lower in doc.id.lower():
                    matches = True
                
                # Check user info
                if not matches and qr_data.get('user'):
                    user = qr_data['user']
                    if (search_lower in user.get('fullName', '').lower() or 
                        search_lower in user.get('emailAddress', '').lower() or 
                        search_lower in user.get('contactNumber', '').lower()):
                        matches = True
                
                # Check vehicle info
                if not matches and qr_data.get('vehicle'):
                    vehicle = qr_data['vehicle']
                    if (search_lower in vehicle.get('ownerFullName', '').lower() or 
                        search_lower in vehicle.get('registrationNumber', '').lower() or 
                        search_lower in vehicle.get('make', '').lower() or 
                        search_lower in vehicle.get('model', '').lower()):
                        matches = True
                
                if not matches:
                    continue
            
            qrs.append(qr_data)
            
        # Sort by last created first
        qrs.sort(key=lambda x: x.get('createdDateTime', ''), reverse=True)
            
        if not qrs:
            messages.info(request, 'No QR codes found matching your criteria')

    except Exception as e:
        messages.error(request, f'Error accessing database: {str(e)}')
        qrs = []

    # Pagination (already defined above)
    
    paginator = Paginator(qrs, items_per_page)
    
    try:
        qrs_page = paginator.page(page)
    except PageNotAnInteger:
        qrs_page = paginator.page(1)
    except EmptyPage:
        qrs_page = paginator.page(paginator.num_pages)

    # Handle export request
    if request.GET.get('export') == 'pdf':
        return export_qrs_pdf(request, qrs)
    
    return render(request, 'manage_qrs.html', {
        'qrs': qrs_page,
        'paginator': paginator,
        'status_filter': status_filter,
        'search_query': search_query,
        'messages': get_message_list(request)
    })

def export_qrs_pdf(request, qrs):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="qr_codes_export.pdf"'

    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Image, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    import pytz

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                          leftMargin=0.5*inch,
                          rightMargin=0.5*inch,
                          topMargin=0.5*inch,
                          bottomMargin=0.5*inch)
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="Title",
        fontSize=14,
        alignment=1,  # CENTER
        fontName="Helvetica-Bold",
        spaceAfter=12,
        textColor=colors.black
    )
    
    date_style = ParagraphStyle(
        name="Date",
        fontSize=10,
        alignment=1,  # CENTER
        fontName="Helvetica",
        spaceAfter=6,
        textColor=colors.darkgrey
    )
    
    # Title and date
    elements.append(Paragraph("QR Codes Export", title_style))
    ist = pytz.timezone('Asia/Kolkata')
    current_datetime = datetime.datetime.now(ist)
    date_str = current_datetime.strftime("%B %d, %Y at %I:%M %p")
    elements.append(Paragraph(f"Generated on: {date_str}", date_style))
    
    if request.GET.get('status'):
        elements.append(Paragraph(f"Status: {request.GET.get('status').capitalize()}", date_style))
    if request.GET.get('search'):
        elements.append(Paragraph(f"Search: {request.GET.get('search')}", date_style))
    
    elements.append(Spacer(1, 24))

    # QR code display settings
    qr_size = 1.5 * inch
    items_per_row = 3
    items_per_page = items_per_row * 3  # 3 rows per page
    
    for i, qr in enumerate(qrs):
        if i > 0 and i % items_per_page == 0:
            elements.append(PageBreak())
        
        if i % items_per_row == 0:
            # Start new row
            row_data = []
        
        # Create QR image
        qr_img = Image(BytesIO(base64.b64decode(qr['qr_code_base64'])),
                      width=qr_size, height=qr_size)
        
        # Create info text
        info = [
            Paragraph(f"<b>QR ID:</b> {qr['doc_id'][:12]}...", styles['Normal']),
            Paragraph(f"<b>Status:</b> {'Active' if qr.get('isAssigned') else 'Inactive'}", styles['Normal'])
        ]
        
        if qr.get('user'):
            info.append(Paragraph(f"<b>User:</b> {qr['user'].get('fullName', '')}", styles['Normal']))
        
        if qr.get('vehicle'):
            info.append(Paragraph(f"<b>Vehicle:</b> {qr['vehicle'].get('registrationNumber', '')}", styles['Normal']))
        
        # Combine QR and info
        item_table = Table([
            [qr_img],
            info
        ], colWidths=qr_size)
        
        row_data.append(item_table)
        
        if (i + 1) % items_per_row == 0 or i == len(qrs) - 1:
            # Complete the row
            row_table = Table([row_data], colWidths=[qr_size]*len(row_data))
            row_table.setStyle(TableStyle([
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ]))
            elements.append(row_table)
            elements.append(Spacer(1, 12))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

def regenerate_qr(request, qr_id):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')

    db = firestore.client()
    
    try:
        # Get existing QR code data
        qr_ref = db.collection('qrcodes').document(qr_id)
        qr_doc = qr_ref.get()
        
        if not qr_doc.exists:
            messages.error(request, 'QR code not found')
            return redirect('manage_qrs')
        
        # Generate the same QR code again
        qr = qrcode.QRCode(
            version=3,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=12,
            border=2,
        )
        qr.add_data(f"{settings.BASE_DOMAIN}/admin/send-notification/{qr_id}/")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#dcbd1f", back_color="#161416")

        # Open template image
        template_path = os.path.join(settings.BASE_DIR, 'sudo_admin', 'static', 'images', 'qr_template.jpg')
        if not os.path.exists(template_path):
            messages.error(request, 'Template image not found')
            return redirect('manage_qrs')

        template_img = PILImage.open(template_path).convert('RGB')
        template_width, template_height = template_img.size

        # Calculate QR code size to occupy 75% of template height
        qr_size = (int(template_height * 0.75), int(template_height * 0.75))

        # Position QR code
        left_margin = int(template_width * 0.07)
        qr_position = (
            left_margin,
            (template_height - qr_size[1]) // 2
        )

        # Paste QR code onto template
        qr_img = qr_img.resize(qr_size, PILImage.Resampling.LANCZOS)
        final_img = template_img.copy()
        final_img.paste(qr_img, qr_position)

        # Save to buffer
        buffer = BytesIO()
        final_img.save(buffer, format="PNG")
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        # Prepare response
        response = HttpResponse(content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="qr_{qr_id}.png"'
        response.write(buffer.getvalue())
        buffer.close()
        
        return response

    except Exception as e:
        messages.error(request, f'Error regenerating QR code: {str(e)}')
        return redirect('manage_qrs')
    
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from io import BytesIO
import qrcode
import base64
import pytz
from datetime import datetime

def export_orders_with_qr(request):
    if request.method != 'POST':
        return HttpResponse("Method not allowed", status=405)
    
    order_ids = request.POST.getlist('order_ids')
    if not order_ids:
        return HttpResponse("No orders selected", status=400)
    
    try:
        # Fetch selected orders
        orders = []
        for order_id in order_ids:
            order_ref = db.collection('orders').document(order_id)
            order_doc = order_ref.get()
            if order_doc.exists:
                order = order_doc.to_dict()
                order['id'] = order_id
                orders.append(order)
        
        if not orders:
            return HttpResponse("No orders found", status=404)
        
        # Create PDF with professional invoice design
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="invoices.pdf"'
        
        buffer = BytesIO()
        # Set smaller margins to utilize more space
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                              leftMargin=0.4*inch,
                              rightMargin=0.4*inch,
                              topMargin=0.4*inch,
                              bottomMargin=0.4*inch)
        
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        
        # Custom styles with SudoTag branding
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=24,
            alignment=1,
            textColor=colors.HexColor("#0d6efd"),
            spaceAfter=5,
            fontName='Helvetica-Bold'
        )
        
        brand_style = ParagraphStyle(
            'Brand',
            parent=styles['Normal'],
            fontSize=20,
            alignment=1,
            textColor=colors.HexColor("#0d6efd"),
            spaceAfter=8,
            fontName='Helvetica-Bold'
        )
        
        company_style = ParagraphStyle(
            'Company',
            parent=styles['Normal'],
            fontSize=10,
            alignment=1,
            textColor=colors.HexColor("#6c757d"),
            spaceAfter=3,
            fontName='Helvetica'
        )
        
        info_style = ParagraphStyle(
            'Info',
            parent=styles['Normal'],
            fontSize=9,
            alignment=1,
            spaceAfter=2,
            textColor=colors.HexColor("#495057")
        )
        
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=9,
            spaceAfter=2,
            textColor=colors.HexColor("#212529")
        )
        
        bold_style = ParagraphStyle(
            'Bold',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold',
            spaceAfter=3,
            textColor=colors.HexColor("#212529")
        )
        
        section_header_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Normal'],
            fontSize=11,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor("#0d6efd"),
            spaceAfter=5
        )
        
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            alignment=1,
            textColor=colors.HexColor("#6c757d"),
            spaceAfter=0
        )
        
        # Add each invoice
        for order in orders:
            # Invoice Header with SudoTag Branding
            elements.append(Paragraph("INVOICE", title_style))
            elements.append(Spacer(1, 5))
            
            # SudoTag Brand Name
            elements.append(Paragraph("SudoTag", brand_style))
            
            # Company Info - Centered with better spacing
            elements.append(Paragraph("Your Trusted Vehicle Management Partner", company_style))
            elements.append(Paragraph("Email: support@sudotag.com", info_style))
            elements.append(Paragraph("Website: www.sudotag.com", info_style))
            elements.append(Spacer(1, 15))
            
            # Invoice Details - Properly aligned in a table
            ist = pytz.timezone('Asia/Kolkata')
            
            # Use order timestamp if available, otherwise use current date
            order_timestamp = order.get('timestamp')
            if order_timestamp:
                # Handle Firestore timestamp
                if hasattr(order_timestamp, 'to_datetime'):
                    order_date = order_timestamp.to_datetime()
                elif hasattr(order_timestamp, 'date') and hasattr(order_timestamp, 'astimezone'):
                    # It's a datetime object
                    order_date = order_timestamp
                else:
                    order_date = now()
                
                # Ensure timezone-aware and convert to IST
                if order_date.tzinfo is None:
                    order_date = pytz.utc.localize(order_date)
                order_date = order_date.astimezone(ist)
            else:
                order_date = now().astimezone(ist)
            
            invoice_data = Table([
                [
                    Paragraph(f"<b>INVOICE #:</b> {order['id']}", normal_style),
                    Paragraph(f"<b>DATE:</b> {order_date.strftime('%B %d, %Y')}", normal_style),
                ]
            ], colWidths=[3.2*inch, 2.3*inch])
            
            invoice_data.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,0), 'TOP'),
                ('ALIGN', (0,0), (0,0), 'LEFT'),
                ('ALIGN', (1,0), (1,0), 'RIGHT'),
                ('LEFTPADDING', (0,0), (0,0), 0),
                ('RIGHTPADDING', (1,0), (1,0), 0),
                ('BOTTOMPADDING', (0,0), (-1,0), 10),
                ('TOPPADDING', (0,0), (-1,0), 5),
            ]))
            
            elements.append(invoice_data)
            elements.append(Spacer(1, 12))
            
            # Bill To and Ship To in two columns - Proper alignment
            address = order.get('address', {})
            
            # Create address tables with proper structure
            bill_to_table = Table([
                [Paragraph("BILL TO:", section_header_style)],
                [Paragraph(order.get('fullName', ''), normal_style)],
                [Paragraph(order.get('mobile', ''), normal_style)],
                [Paragraph(f"{address.get('houseNumber', '')} {address.get('street', '')}", normal_style)],
                [Paragraph(f"{address.get('city', '')}, {address.get('state', '')}", normal_style)],
                [Paragraph(f"PIN: {address.get('pincode', '')}", normal_style)],
            ], colWidths=[2.8*inch])
            
            bill_to_table.setStyle(TableStyle([
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ]))
            
            ship_to_table = Table([
                [Paragraph("SHIP TO:", section_header_style)],
                [Paragraph(order.get('fullName', ''), normal_style)],
                [Paragraph(f"{address.get('houseNumber', '')} {address.get('street', '')}", normal_style)],
                [Paragraph(f"{address.get('city', '')}, {address.get('state', '')}", normal_style)],
                [Paragraph(f"PIN: {address.get('pincode', '')}", normal_style)],
            ], colWidths=[2.8*inch])
            
            ship_to_table.setStyle(TableStyle([
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ]))
            
            # Combine both address tables side by side
            address_table = Table([
                [bill_to_table, ship_to_table]
            ], colWidths=[2.75*inch, 2.75*inch])
            
            address_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,0), 'TOP'),
                ('ALIGN', (0,0), (0,0), 'LEFT'),
                ('ALIGN', (1,0), (1,0), 'LEFT'),
                ('LEFTPADDING', (0,0), (-1,0), 0),
                ('RIGHTPADDING', (0,0), (-1,0), 0),
            ]))
            
            elements.append(address_table)
            elements.append(Spacer(1, 15))
            
            # Items Table - Proper column widths and alignment
            # Total width should be approximately 5.5 inches (page width minus margins)
            items_header = Table([
                ['ITEM #', 'DESCRIPTION', 'QTY', 'PRICE', 'TOTAL']
            ], colWidths=[0.6*inch, 3.0*inch, 0.6*inch, 0.8*inch, 0.8*inch])
            
            items_header.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0d6efd")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ALIGN', (0,0), (0,0), 'CENTER'),
                ('ALIGN', (1,0), (1,0), 'LEFT'),
                ('ALIGN', (2,0), (2,0), 'CENTER'),
                ('ALIGN', (3,0), (3,0), 'RIGHT'),
                ('ALIGN', (4,0), (4,0), 'RIGHT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('TOPPADDING', (0,0), (-1,0), 6),
                ('RIGHTPADDING', (3,0), (4,0), 8),
            ]))
            elements.append(items_header)
            
            # Order Item - Make sure quantity is included
            amount = float(order.get('amount', 0))
            quantity = order.get('quantity', 1)
            unit_price = amount / quantity if quantity > 0 else amount
            
            # Use "Rs." instead of ₹ symbol for better PDF compatibility
            item_data = Table([
                ['1', order.get('selectedItem', '').upper(), str(quantity), f"Rs. {unit_price:.2f}", f"Rs. {amount:.2f}"]
            ], colWidths=[0.6*inch, 3.0*inch, 0.6*inch, 0.8*inch, 0.8*inch])
            
            item_data.setStyle(TableStyle([
                ('ALIGN', (0,0), (0,0), 'CENTER'),
                ('ALIGN', (1,0), (1,0), 'LEFT'),
                ('ALIGN', (2,0), (2,0), 'CENTER'),
                ('ALIGN', (3,0), (3,0), 'RIGHT'),
                ('ALIGN', (4,0), (4,0), 'RIGHT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica'),
                ('FONTSIZE', (0,0), (-1,0), 9),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('TOPPADDING', (0,0), (-1,0), 6),
                ('GRID', (0,0), (-1,0), 0.5, colors.HexColor("#e5e7eb")),
                ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
                ('RIGHTPADDING', (3,0), (4,0), 8),
            ]))
            elements.append(item_data)
            elements.append(Spacer(1, 12))
            
            # Grand Total - Proper alignment and label
            grand_total_data = Table([
                ['', '', '', Paragraph("<b>GRAND TOTAL:</b>", bold_style), Paragraph(f"<b>Rs. {amount:.2f}</b>", bold_style)]
            ], colWidths=[0.6*inch, 3.0*inch, 0.6*inch, 1.0*inch, 0.8*inch])
            
            grand_total_data.setStyle(TableStyle([
                ('ALIGN', (3,0), (3,0), 'RIGHT'),
                ('ALIGN', (4,0), (4,0), 'RIGHT'),
                ('VALIGN', (3,0), (4,0), 'MIDDLE'),
                ('FONTSIZE', (3,0), (4,0), 11),
                ('BOTTOMPADDING', (0,0), (-1,0), 10),
                ('TOPPADDING', (0,0), (-1,0), 8),
                ('TEXTCOLOR', (3,0), (4,0), colors.HexColor("#0d6efd")),
                ('FONTNAME', (3,0), (4,0), 'Helvetica-Bold'),
                ('RIGHTPADDING', (4,0), (4,0), 8),
            ]))
            elements.append(grand_total_data)
            elements.append(Spacer(1, 15))
            
            # Footer with SudoTag branding
            elements.append(Spacer(1, 20))
            footer_text = "www.sudotag.com | support@sudotag.com"
            footer = Paragraph(footer_text, footer_style)
            elements.append(footer)
            
            # SudoTag brand name at bottom
            elements.append(Spacer(1, 5))
            elements.append(Paragraph("SudoTag", ParagraphStyle(
                'FooterCompany',
                parent=styles['Normal'],
                fontSize=12,
                alignment=1,
                textColor=colors.HexColor("#0d6efd"),
                fontName='Helvetica-Bold'
            )))
            elements.append(Paragraph("Thank you for your business!", ParagraphStyle(
                'ThankYou',
                parent=styles['Normal'],
                fontSize=9,
                alignment=1,
                textColor=colors.HexColor("#6c757d"),
                spaceAfter=0
            )))
            
            # Add page break if not last order
            if order != orders[-1]:
                elements.append(PageBreak())
        
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        response.write(pdf)
        return response
    
    except Exception as e:
        import traceback
        print(f"Error: {str(e)}")
        print(traceback.format_exc())
        return HttpResponse(f"Error generating PDF: {str(e)}", status=500)


def assign_qr(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')

    db = firestore.client()
    
    if request.method == 'POST':
        try:
            qr_id = request.POST.get('qr_id')
            user_id = request.POST.get('user_id')
            vehicle_id = request.POST.get('vehicle_id')
            
            if not all([qr_id, user_id, vehicle_id]):
                messages.error(request, 'All fields are required')
                return redirect('assign_qr')
            
            # Verify QR exists and is not assigned
            qr_ref = db.collection('qrcodes').document(qr_id)
            qr_doc = qr_ref.get()
            
            if not qr_doc.exists:
                messages.error(request, 'QR code not found')
                return redirect('assign_qr')
            
            qr_data = qr_doc.to_dict()
            if qr_data.get('isAssigned', False):
                messages.error(request, 'QR code is already assigned')
                return redirect('assign_qr')
            
            # Verify user exists
            user_ref = db.collection('users').document(user_id)
            if not user_ref.get().exists:
                messages.error(request, 'User not found')
                return redirect('assign_qr')
            
            # Verify vehicle exists and belongs to user
            vehicle_ref = db.collection('vehicles').document(vehicle_id)
            vehicle_doc = vehicle_ref.get()
            
            if not vehicle_doc.exists:
                messages.error(request, 'Vehicle not found')
                return redirect('assign_qr')
            
            vehicle_data = vehicle_doc.to_dict()
            if vehicle_data.get('ownerId') != user_id:
                messages.error(request, 'Vehicle does not belong to the selected user')
                return redirect('assign_qr')
            
            # Update QR code assignment with IST timestamp
            ist = pytz.timezone('Asia/Kolkata')
            qr_ref.update({
                'isAssigned': True,
                'userID': user_id,
                'vehicleID': vehicle_id,
                'assignedAt': now().astimezone(ist),
                'lastUpdated': now().astimezone(ist)
            })
            
            # Update vehicle with QR code ID
            vehicle_ref.update({
                'qrCodeId': qr_id,
                'isQrGenerated': True
            })
            
            # Update user to enable ID check
            user_ref.update({
                'enableIdCheck': True
            })
            
            # Success message - stay on same page
            messages.success(request, f'QR code {qr_id} successfully assigned to user!')
            
            # Return the same form but with success message
            return redirect('assign_qr')
            
        except Exception as e:
            messages.error(request, f'Error assigning QR code: {str(e)}')
            return redirect('assign_qr')
    
    # GET request - show assignment form
    try:
        # Get search parameters
        search_qr = request.GET.get('search_qr', '')
        search_user = request.GET.get('search_user', '')
        
        # Get unassigned QR codes with search filter
        qr_query = db.collection('qrcodes').where(filter=FieldFilter('isAssigned', '==', False))
        
        qr_list = []
        for qr in qr_query.stream():
            qr_data = qr.to_dict()
            qr_data['id'] = qr.id
            
            # Apply QR search filter if provided
            if search_qr and search_qr.lower() not in qr.id.lower():
                continue
                
            qr_list.append(qr_data)
        
        # Get users with vehicles but no QR assigned
        users_with_vehicles = []
        users_query = db.collection('users')
        
        # If user search is provided, filter users
        if search_user:
            users_ref = users_query.stream()
        else:
            users_ref = users_query.stream()
        
        for user in users_ref:
            user_data = user.to_dict()
            user_data['id'] = user.id
            
            # Apply user search filter
            if search_user:
                search_lower = search_user.lower()
                matches_search = (
                    search_lower in user_data.get('fullName', '').lower() or
                    search_lower in user_data.get('emailAddress', '').lower() or
                    search_lower in user.id.lower()
                )
                if not matches_search:
                    continue
            
            # Get user's vehicles without QR codes
            vehicles_ref = db.collection('vehicles')\
                .where(filter=FieldFilter('ownerId', '==', user.id))\
                .where(filter=FieldFilter('isQrGenerated', '==', False))\
                .stream()
            
            user_vehicles = []
            for vehicle in vehicles_ref:
                vehicle_data = vehicle.to_dict()
                vehicle_data['id'] = vehicle.id
                user_vehicles.append(vehicle_data)
            
            if user_vehicles:
                user_data['vehicles'] = user_vehicles
                users_with_vehicles.append(user_data)
        
        context = {
            'unassigned_qrs': qr_list,
            'users_with_vehicles': users_with_vehicles,
            'search_qr': search_qr,
            'search_user': search_user,
            'messages': get_message_list(request)
        }
        
        return render(request, 'assign_qr.html', context)
        
    except Exception as e:
        messages.error(request, f'Error loading data: {str(e)}')
        return render(request, 'assign_qr.html', {
            'unassigned_qrs': [],
            'users_with_vehicles': [],
            'search_qr': '',
            'search_user': '',
            'messages': get_message_list(request)
        })

def search_qr_codes(request):
    """AJAX endpoint to search QR codes"""
    if not request.session.get('admin'):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        search_term = request.GET.get('q', '')
        db = firestore.client()
        
        qr_query = db.collection('qrcodes')\
            .where(filter=FieldFilter('isAssigned', '==', False))\
            .stream()
        
        qr_codes = []
        for qr in qr_query:
            qr_data = qr.to_dict()
            qr_data['id'] = qr.id
            
            # Apply search filter
            if search_term and search_term.lower() not in qr.id.lower():
                continue
                
            qr_codes.append({
                'id': qr.id,
                'createdDateTime': qr_data.get('createdDateTime', ''),
                'full_id': qr.id  # Send full ID for display
            })
        
        return JsonResponse({'qr_codes': qr_codes})
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def search_users(request):
    """AJAX endpoint to search users with unassigned vehicles"""
    if not request.session.get('admin'):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        search_term = request.GET.get('q', '')
        db = firestore.client()
        
        users_ref = db.collection('users').stream()
        
        users = []
        for user in users_ref:
            user_data = user.to_dict()
            user_data['id'] = user.id
            
            # Apply search filter
            if search_term:
                search_lower = search_term.lower()
                matches_search = (
                    search_lower in user_data.get('fullName', '').lower() or
                    search_lower in user_data.get('emailAddress', '').lower() or
                    search_lower in user.id.lower()
                )
                if not matches_search:
                    continue
            
            # Check if user has unassigned vehicles
            vehicles_ref = db.collection('vehicles')\
                .where(filter=FieldFilter('ownerId', '==', user.id))\
                .where(filter=FieldFilter('isQrGenerated', '==', False))\
                .limit(1)\
                .stream()
            
            has_unassigned_vehicles = any(True for _ in vehicles_ref)
            
            if has_unassigned_vehicles:
                users.append({
                    'id': user.id,
                    'fullName': user_data.get('fullName', ''),
                    'emailAddress': user_data.get('emailAddress', ''),
                    'full_id': user.id  # Send full ID for display
                })
        
        return JsonResponse({'users': users})
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def get_user_vehicles(request, user_id):
    """AJAX endpoint to get vehicles for a specific user"""
    if not request.session.get('admin'):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        db = firestore.client()
        vehicles_ref = db.collection('vehicles')\
            .where(filter=FieldFilter('ownerId', '==', user_id))\
            .where(filter=FieldFilter('isQrGenerated', '==', False))\
            .stream()
        
        vehicles = []
        for vehicle in vehicles_ref:
            vehicle_data = vehicle.to_dict()
            vehicle_data['id'] = vehicle.id
            vehicles.append(vehicle_data)
        
        return JsonResponse({'vehicles': vehicles})
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# Define your collections
COLLECTIONS = [
    'ads', 'chats', 'daily_usage', 'notifications', 'orders', 'payments', 'qrcodes', 'users', 'vehicles', 'vehicleDocuments'
]

def verify_delete_pin(request):
    """PIN verification page for delete data access"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if request.method == 'POST':
        pin = request.POST.get('pin', '').strip()
        if pin == '4455':
            request.session['delete_data_verified'] = True
            next_url = request.POST.get('next', '/admin/delete-data/')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid PIN. Please try again.')
    
    return render(request, 'verify_pin.html')

def delete_data(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    # Check PIN verification
    if not request.session.get('delete_data_verified'):
        return redirect(f'/admin/verify-delete-pin/?next={request.path}')
    
    # Get collection counts
    collection_counts = {}
    for collection in COLLECTIONS:
        try:
            docs = db.collection(collection).stream()
            collection_counts[collection] = len(list(docs))
        except Exception as e:
            collection_counts[collection] = f"Error: {str(e)}"
    
    # Get Firebase Auth users count
    auth_users_count = 0
    try:
        # List all Firebase Auth users (limited to first 1000 for count)
        page = auth.list_users(max_results=1000)
        count = 0
        while page:
            count += len(list(page.users))
            if hasattr(page, 'has_next_page') and page.has_next_page:
                page = page.get_next_page()
            else:
                break
        auth_users_count = count
    except Exception as e:
        auth_users_count = f"Error: {str(e)}"
    
    context = {
        'collections': COLLECTIONS,
        'collection_counts': collection_counts,
        'auth_users_count': auth_users_count,
    }
    return render(request, 'delete_data.html', context)

def delete_collection(request, collection_name):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if not request.session.get('delete_data_verified'):
        return redirect(f'/admin/verify-delete-pin/?next={request.path}')
    
    if collection_name not in COLLECTIONS:
        messages.error(request, 'Invalid collection name')
        return redirect('delete_data')
    
    try:
        # Get all documents in the collection
        docs = db.collection(collection_name).stream()
        deleted_count = 0
        
        # Delete each document
        for doc in docs:
            doc.reference.delete()
            deleted_count += 1
        
        messages.success(request, f'Successfully deleted {deleted_count} documents from {collection_name}')
    
    except Exception as e:
        messages.error(request, f'Error deleting collection {collection_name}: {str(e)}')
    
    return redirect('delete_data')

def delete_document(request, collection_name, document_id):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if not request.session.get('delete_data_verified'):
        return redirect(f'/admin/verify-delete-pin/?next={request.path}')
    
    if collection_name not in COLLECTIONS:
        messages.error(request, 'Invalid collection name')
        return redirect('delete_data')
    
    # Handle both GET (from view_collection) and POST (from delete_data form)
    if request.method == 'POST':
        # Get collection and document_id from POST data
        collection_name = request.POST.get('collection_name', collection_name)
        document_id = request.POST.get('document_id', document_id)
    
    try:
        # Delete the specific document
        doc_ref = db.collection(collection_name).document(document_id)
        doc = doc_ref.get()
        
        if doc.exists:
            doc_ref.delete()
            messages.success(request, f'Successfully deleted document {document_id} from {collection_name}')
        else:
            messages.error(request, f'Document {document_id} not found in {collection_name}')
    
    except Exception as e:
        messages.error(request, f'Error deleting document: {str(e)}')
    
    # Redirect back to view_collection if coming from there, otherwise to delete_data
    if 'view-collection' in request.META.get('HTTP_REFERER', ''):
        return redirect('view_collection', collection_name=collection_name)
    return redirect('delete_data')

@csrf_exempt
def bulk_delete(request):
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'})
    
    if not request.session.get('delete_data_verified'):
        return JsonResponse({'success': False, 'error': 'PIN verification required'})
    
    if request.method == 'POST':
        try:
            data = request.POST
            collections_to_delete = data.getlist('collections[]')
            confirm_text = data.get('confirm_text', '')
            
            # Safety check - require confirmation text
            if confirm_text != 'DELETE ALL':
                return JsonResponse({
                    'success': False, 
                    'error': 'Confirmation text incorrect. Please type "DELETE ALL" to confirm.'
                })
            
            total_deleted = 0
            results = {}
            
            for collection_name in collections_to_delete:
                if collection_name in COLLECTIONS:
                    try:
                        docs = db.collection(collection_name).stream()
                        deleted_count = 0
                        
                        for doc in docs:
                            doc.reference.delete()
                            deleted_count += 1
                        
                        results[collection_name] = deleted_count
                        total_deleted += deleted_count
                    
                    except Exception as e:
                        results[collection_name] = f"Error: {str(e)}"
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully deleted {total_deleted} documents across {len(collections_to_delete)} collections',
                'results': results
            })
        
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

# Advanced: Delete with conditions
def delete_with_conditions(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if request.method == 'POST':
        collection_name = request.POST.get('collection_name')
        field = request.POST.get('field')
        operator = request.POST.get('operator')
        value = request.POST.get('value')
        
        if collection_name not in COLLECTIONS:
            messages.error(request, 'Invalid collection name')
            return redirect('delete_data')
        
        try:
            collection_ref = db.collection(collection_name)
            
            # Build query based on operator
            if operator == '==':
                query = collection_ref.where(field, '==', value)
            elif operator == '!=':
                query = collection_ref.where(field, '!=', value)
            elif operator == '>':
                query = collection_ref.where(field, '>', value)
            elif operator == '<':
                query = collection_ref.where(field, '<', value)
            elif operator == '>=':
                query = collection_ref.where(field, '>=', value)
            elif operator == '<=':
                query = collection_ref.where(field, '<=', value)
            elif operator == 'array_contains':
                query = collection_ref.where(field, 'array_contains', value)
            else:
                messages.error(request, 'Invalid operator')
                return redirect('delete_data')
            
            docs = query.stream()
            deleted_count = 0
            
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1
            
            messages.success(request, f'Deleted {deleted_count} documents from {collection_name} where {field} {operator} {value}')
        
        except Exception as e:
            messages.error(request, f'Error deleting documents: {str(e)}')
    
    return redirect('delete_data')


def view_auth_users(request):
    """View Firebase Authentication users"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if not request.session.get('delete_data_verified'):
        return redirect(f'/admin/verify-delete-pin/?next={request.path}')
    
    try:
        # List all Firebase Auth users
        auth_users_list = []
        page = auth.list_users(max_results=1000)
        
        while page:
            for user in page.users:
                auth_users_list.append({
                    'uid': user.uid,
                    'email': user.email or 'No email',
                    'display_name': user.display_name or 'No name',
                    'phone_number': user.phone_number or 'No phone',
                    'disabled': user.disabled,
                    'email_verified': user.email_verified if hasattr(user, 'email_verified') else False,
                    'creation_timestamp': user.user_metadata.creation_timestamp if hasattr(user, 'user_metadata') and hasattr(user.user_metadata, 'creation_timestamp') else None,
                })
            
            # Get next page
            if hasattr(page, 'has_next_page') and page.has_next_page:
                page = page.get_next_page()
            else:
                break
        
        context = {
            'auth_users': auth_users_list,
            'total_count': len(auth_users_list),
        }
        return render(request, 'view_auth_users.html', context)
    
    except Exception as e:
        messages.error(request, f'Error accessing Firebase Auth users: {str(e)}')
        import traceback
        print(f"Error in view_auth_users: {str(e)}")
        print(traceback.format_exc())
        return redirect('delete_data')

def delete_auth_user(request, uid):
    """Delete a single Firebase Authentication user"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if not request.session.get('delete_data_verified'):
        return redirect(f'/admin/verify-delete-pin/?next={request.path}')
    
    try:
        auth.delete_user(uid)
        messages.success(request, f'Successfully deleted Firebase Auth user: {uid}')
    except Exception as e:
        messages.error(request, f'Error deleting Firebase Auth user: {str(e)}')
    
    return redirect('view_auth_users')

@csrf_exempt
def bulk_delete_auth_users(request):
    """Bulk delete Firebase Authentication users"""
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'})
    
    if not request.session.get('delete_data_verified'):
        return JsonResponse({'success': False, 'error': 'PIN verification required'})
    
    if request.method == 'POST':
        try:
            data = request.POST
            uids = data.getlist('uids[]')
            confirm_text = data.get('confirm_text', '')
            
            # Safety check
            if confirm_text != 'DELETE ALL':
                return JsonResponse({
                    'success': False, 
                    'error': 'Confirmation text incorrect. Please type "DELETE ALL" to confirm.'
                })
            
            if not uids:
                return JsonResponse({
                    'success': False,
                    'error': 'No users selected'
                })
            
            deleted_count = 0
            errors = []
            
            for uid in uids:
                try:
                    auth.delete_user(uid)
                    deleted_count += 1
                except Exception as e:
                    errors.append(f"Error deleting {uid}: {str(e)}")
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully deleted {deleted_count} Firebase Auth user(s)',
                'deleted_count': deleted_count,
                'errors': errors if errors else None
            })
        
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@ensure_csrf_cookie
def manage_daily_usage(request):
    """Manage daily usage records - view and update"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    db = firestore.client()
    ist = pytz.timezone('Asia/Kolkata')
    
    # Handle update
    if request.method == 'POST' and 'update_usage' in request.POST:
        doc_id = request.POST.get('doc_id')
        
        try:
            usage_ref = db.collection('daily_usage').document(doc_id)
            update_data = {
                'last_updated': now().astimezone(ist),
            }
            
            # Update all count fields dynamically
            count_fields = ['calls_count', 'sms_count', 'dailyChatMessageCount']
            for field in count_fields:
                value = request.POST.get(field, '').strip()
                if value != '':
                    try:
                        update_data[field] = int(value)
                    except (ValueError, TypeError):
                        update_data[field] = 0
            
            usage_ref.update(update_data)
            messages.success(request, f'Daily usage updated successfully for {doc_id}')
            # Redirect to prevent duplicate submissions and ensure messages show on correct page
            # Preserve search parameters if they exist
            redirect_url = 'manage_daily_usage'
            if request.GET.get('search') or request.GET.get('date') or request.GET.get('page'):
                from urllib.parse import urlencode
                params = {}
                if request.GET.get('search'):
                    params['search'] = request.GET.get('search')
                if request.GET.get('date'):
                    params['date'] = request.GET.get('date')
                if params:
                    redirect_url = f"{redirect_url}?{urlencode(params)}"
            return redirect(redirect_url)
        except Exception as e:
            messages.error(request, f'Error updating daily usage: {str(e)}')
            # Redirect even on error to show message on correct page
            redirect_url = 'manage_daily_usage'
            if request.GET.get('search') or request.GET.get('date'):
                from urllib.parse import urlencode
                params = {}
                if request.GET.get('search'):
                    params['search'] = request.GET.get('search')
                if request.GET.get('date'):
                    params['date'] = request.GET.get('date')
                if params:
                    redirect_url = f"{redirect_url}?{urlencode(params)}"
            return redirect(redirect_url)
    
    # Get search/filter parameters
    search_term = request.GET.get('search', '').strip()
    search_date = request.GET.get('date', '').strip()
    
    try:
        # Fetch daily usage records
        usage_ref = db.collection('daily_usage')
        docs = list(usage_ref.stream())  # Convert to list to iterate multiple times
        
        daily_usage_list = []
        user_cache = {}
        
        # First pass: collect all user IDs and fetch user data
        user_ids_to_fetch = set()
        for doc in docs:
            usage_data = doc.to_dict() or {}
            user_id = usage_data.get('userId', '')
            if user_id:
                user_ids_to_fetch.add(user_id)
        
        # Fetch all user data at once
        for user_id in user_ids_to_fetch:
            try:
                user_doc = db.collection('users').document(user_id).get()
                user_cache[user_id] = user_doc.to_dict() if user_doc.exists else None
            except:
                user_cache[user_id] = None
        
        # Second pass: process documents with user data
        for doc in docs:
            usage_data = doc.to_dict() or {}
            usage_data['doc_id'] = doc.id
            
            # Get identifier (userId or qr_id)
            user_id = usage_data.get('userId', '')
            qr_id = usage_data.get('qr_id', '')
            identifier = user_id or qr_id or doc.id
            
            # Apply filters
            if search_term:
                search_lower = search_term.lower()
                matches = False
                
                # Check identifier fields
                if (search_lower in identifier.lower() or 
                    search_lower in user_id.lower() or 
                    search_lower in qr_id.lower()):
                    matches = True
                
                # Check user details if userId exists
                if not matches and user_id and user_id in user_cache:
                    user_data = user_cache[user_id]
                    if user_data:
                        user_name = (user_data.get('fullName', '') or '').lower()
                        user_email = (user_data.get('emailAddress', '') or '').lower()
                        if search_lower in user_name or search_lower in user_email:
                            matches = True
                
                if not matches:
                    continue
            
            # Check date filter
            date_value = usage_data.get('date', '')
            if search_date and search_date not in date_value:
                # Also check lastUpdated timestamp
                last_updated = usage_data.get('lastUpdated') or usage_data.get('last_updated')
                if last_updated:
                    try:
                        if hasattr(last_updated, 'date'):
                            usage_date = last_updated.date().strftime('%Y-%m-%d')
                        elif isinstance(last_updated, str):
                            # Try to parse string date
                            usage_date = last_updated[:10] if len(last_updated) >= 10 else ''
                        else:
                            usage_date = ''
                        if search_date not in usage_date:
                            continue
                    except:
                        continue
                else:
                    continue
            
            # Attach user details if userId exists
            if user_id:
                usage_data['user'] = user_cache.get(user_id)
            
            # Ensure all count fields are integers
            usage_data['calls_count'] = int(usage_data.get('calls_count', 0) or 0)
            usage_data['sms_count'] = int(usage_data.get('sms_count', 0) or 0)
            usage_data['dailyChatMessageCount'] = int(usage_data.get('dailyChatMessageCount', 0) or 0)
            
            # Store identifier for display
            usage_data['identifier'] = identifier
            usage_data['identifier_type'] = 'User ID' if user_id else ('QR ID' if qr_id else 'Document ID')
            
            daily_usage_list.append(usage_data)
        
        # Sort by last_updated or date (newest first)
        def get_sort_key(x):
            last_updated = x.get('lastUpdated') or x.get('last_updated')
            if last_updated:
                if hasattr(last_updated, 'timestamp'):
                    return last_updated.timestamp()
                elif isinstance(last_updated, str):
                    try:
                        from datetime import datetime
                        return datetime.fromisoformat(last_updated.replace('Z', '+00:00')).timestamp()
                    except:
                        pass
            date_str = x.get('date', '')
            return date_str if date_str else '0'
        
        daily_usage_list.sort(key=get_sort_key, reverse=True)
        
        # Pagination
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        page = request.GET.get('page', 1)
        paginator = Paginator(daily_usage_list, 20)
        
        try:
            usage_page = paginator.page(page)
        except PageNotAnInteger:
            usage_page = paginator.page(1)
        except EmptyPage:
            usage_page = paginator.page(paginator.num_pages)
        
        context = {
            'daily_usage': usage_page,
            'paginator': paginator,
            'search_term': search_term,
            'search_date': search_date,
            'messages': get_message_list(request),
        }
        return render(request, 'manage_daily_usage.html', context)
    
    except Exception as e:
        messages.error(request, f'Error accessing daily usage: {str(e)}')
        return render(request, 'manage_daily_usage.html', {
            'daily_usage': [],
            'paginator': None,
            'search_term': '',
            'search_date': '',
            'messages': get_message_list(request),
        })

def view_collection(request, collection_name):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    if not request.session.get('delete_data_verified'):
        return redirect(f'/admin/verify-delete-pin/?next={request.path}')
    
    if collection_name not in COLLECTIONS:
        messages.error(request, 'Invalid collection name')
        return redirect('delete_data')
    
    try:
        docs = db.collection(collection_name).stream()
        documents = []
        
        for doc in docs:
            doc_data = doc.to_dict()
            doc_data['id'] = doc.id
            documents.append(doc_data)
        
        context = {
            'collection_name': collection_name,
            'documents': documents,
        }
        return render(request, 'view_collection.html', context)
    
    except Exception as e:
        messages.error(request, f'Error accessing collection: {str(e)}')
        return redirect('delete_data')

# views.py - Add these imports
import cloudinary.uploader
from datetime import datetime
import uuid
import base64
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
# views.py - Update the manage_ads function
def manage_ads(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    # Get all ads from the ads collection
    ads_data = {}
    
    try:
        ads_ref = db.collection('ads')
        ads_docs = ads_ref.stream()
        
        for doc in ads_docs:
            data = doc.to_dict()
            doc_id = doc.id
            print(f"Debug: Found document {doc_id} with data: {data}")  # Debug
            
            # Handle different ad types from ALL documents
            if 'banner_Ads' in data and isinstance(data['banner_Ads'], list):
                # Add is_active field if missing and convert timestamp
                for ad in data['banner_Ads']:
                    if 'is_active' not in ad:
                        ad['is_active'] = True
                    # Keep timestamp as datetime object for template filtering
                    # Don't convert to string - let template handle with to_ist filter
                        ad['timestamp'] = ad['timestamp'].strftime("%B %d, %Y at %I:%M:%S %p UTC+5:30")
                
                # Append to existing list or create new
                if 'banner_ads' not in ads_data:
                    ads_data['banner_ads'] = []
                ads_data['banner_ads'].extend(data['banner_Ads'])
                
            if 'marquee_Ads' in data and isinstance(data['marquee_Ads'], list):
                for ad in data['marquee_Ads']:
                    if 'is_active' not in ad:
                        ad['is_active'] = True
                    # Keep timestamp as datetime object for template filtering
                    # Don't convert to string - let template handle with to_ist filter
                
                if 'marquee_ads' not in ads_data:
                    ads_data['marquee_ads'] = []
                ads_data['marquee_ads'].extend(data['marquee_Ads'])
                
            if 'popup_Ads' in data and isinstance(data['popup_Ads'], list):
                for ad in data['popup_Ads']:
                    if 'is_active' not in ad:
                        ad['is_active'] = True
                    # Keep timestamp as datetime object for template filtering
                    # Don't convert to string - let template handle with to_ist filter
                
                if 'popup_ads' not in ads_data:
                    ads_data['popup_ads'] = []
                ads_data['popup_ads'].extend(data['popup_Ads'])
                
    except Exception as e:
        print(f"Error loading ads: {str(e)}")
        messages.error(request, f'Error loading ads: {str(e)}')
    
    # Initialize empty lists if not found
    ads_data.setdefault('banner_ads', [])
    ads_data.setdefault('marquee_ads', [])
    ads_data.setdefault('popup_ads', [])
    
    print(f"Debug: Final ads data - Banner: {len(ads_data['banner_ads'])}, Marquee: {len(ads_data['marquee_ads'])}, Popup: {len(ads_data['popup_ads'])}")  # Debug
    
    return render(request, 'manage_ads.html', {
        'ads_data': ads_data,
        'messages': get_message_list(request)
    })

# views.py - Update the add_ad function to handle images for all ad types
@csrf_exempt
def add_ad(request):
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'})
    
    if request.method == 'POST':
        try:
            ad_type = request.POST.get('ad_type')  # banner, marquee, popup
            image_file = request.FILES.get('image_file')
            message = request.POST.get('message', '')
            link_url = request.POST.get('link_url', '')
            
            print(f"Debug: Adding {ad_type} ad - message: {message}, link: {link_url}")
            
            if not ad_type:
                return JsonResponse({'success': False, 'error': 'Ad type is required'})
            
            # Require image for ALL ad types
            if not image_file:
                return JsonResponse({'success': False, 'error': 'Image is required for all ad types'})
            
            # Generate unique ID
            ad_id = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8')[:12]
            
            image_url = ""
            # Upload image for ALL ad types
            if image_file:
                try:
                    upload_result = cloudinary.uploader.upload(
                        image_file,
                        folder=f"{ad_type}_ads",
                        public_id=f"{ad_type}_{ad_id}",
                        overwrite=True,
                        resource_type="image"
                    )
                    image_url = upload_result['secure_url']
                    print(f"Debug: Image uploaded to: {image_url}")
                except Exception as upload_error:
                    return JsonResponse({'success': False, 'error': f'Image upload failed: {str(upload_error)}'})

            # Create ad data - ALL types have image_url now
            ad_data = {
                'id': ad_id,
                'message': message,
                'link': link_url,
                'image_url': image_url,  # This line ensures ALL ad types get image_url
                'timestamp': datetime.datetime.now().strftime("%B %d, %Y at %I:%M:%S %p UTC+5:30"),
                'is_active': True
            }
            
            # Find the correct document ID (use the one that already exists)
            ads_ref = db.collection('ads')
            ads_docs = list(ads_ref.stream())
            
            target_doc_id = None
            
            # Look for existing document with any ads field
            for doc in ads_docs:
                data = doc.to_dict()
                if 'banner_Ads' in data or 'marquee_Ads' in data or 'popup_Ads' in data:
                    target_doc_id = doc.id
                    break
            
            # If no existing document found, use the first one or create new
            if not target_doc_id and ads_docs:
                target_doc_id = ads_docs[0].id
            elif not target_doc_id:
                target_doc_id = 'Tj0a1J50TeKUVjmWvg26'  # Use a default ID
            
            print(f"Debug: Using document ID: {target_doc_id}")
            
            # Get or create the main ads document
            ads_ref = db.collection('ads').document(target_doc_id)
            ads_doc = ads_ref.get()
            
            if ads_doc.exists:
                current_data = ads_doc.to_dict()
            else:
                current_data = {}
            
            # Update the specific ad type array
            field_name = f"{ad_type}_Ads"
            if field_name not in current_data:
                current_data[field_name] = []
            
            current_data[field_name].append(ad_data)
            
            # Save to Firestore
            ads_ref.set(current_data)
            
            return JsonResponse({'success': True, 'message': f'{ad_type.capitalize()} ad added successfully'})
            
        except Exception as e:
            print(f"Debug: Error in add_ad: {str(e)}")
            import traceback
            print(f"Debug: Traceback: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

# Update the update_ad function to handle images for all ad types
@csrf_exempt
def update_ad(request):
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'})
    
    if request.method == 'POST':
        try:
            ad_type = request.POST.get('ad_type')
            ad_id = request.POST.get('ad_id')
            message = request.POST.get('message')
            link_url = request.POST.get('link_url')
            is_active = request.POST.get('is_active')
            image_file = request.FILES.get('image_file')
            
            print(f"Debug: Updating {ad_type} ad {ad_id}")
            
            # Find the correct document across all ads documents
            ads_ref = db.collection('ads')
            ads_docs = list(ads_ref.stream())
            
            updated = False
            target_doc_id = None
            
            for doc in ads_docs:
                current_data = doc.to_dict()
                field_name = f"{ad_type}_Ads"
                
                if field_name in current_data and isinstance(current_data[field_name], list):
                    # Find and update the specific ad
                    for ad in current_data[field_name]:
                        if ad.get('id') == ad_id:
                            if message is not None:
                                ad['message'] = message
                            if link_url is not None:
                                ad['link'] = link_url
                            if is_active is not None:
                                ad['is_active'] = is_active == 'true'
                            
                            # Handle image update for ALL ad types
                            if image_file:
                                try:
                                    upload_result = cloudinary.uploader.upload(
                                        image_file,
                                        folder=f"{ad_type}_ads",
                                        public_id=f"{ad_type}_{ad_id}",
                                        overwrite=True,
                                        resource_type="image"
                                    )
                                    ad['image_url'] = upload_result['secure_url']
                                except Exception as upload_error:
                                    return JsonResponse({'success': False, 'error': f'Image upload failed: {str(upload_error)}'})
                            
                            ad['timestamp'] = datetime.datetime.now().strftime("%B %d, %Y at %I:%M:%S %p UTC+5:30")
                            updated = True
                            target_doc_id = doc.id
                            break
                
                if updated:
                    break
            
            if not updated:
                return JsonResponse({'success': False, 'error': 'Ad not found'})
            
            # Save updated data
            if target_doc_id:
                ads_ref.document(target_doc_id).set(current_data)
            
            return JsonResponse({'success': True, 'message': f'{ad_type.capitalize()} ad updated successfully'})
            
        except Exception as e:
            print(f"Debug: Error in update_ad: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def delete_ad(request):
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'})
    
    if request.method == 'POST':
        try:
            ad_type = request.POST.get('ad_type')
            ad_id = request.POST.get('ad_id')
            
            print(f"Debug: Deleting {ad_type} ad {ad_id}")
            
            # Find the correct document across all ads documents
            ads_ref = db.collection('ads')
            ads_docs = list(ads_ref.stream())
            
            deleted = False
            target_doc_id = None
            
            for doc in ads_docs:
                current_data = doc.to_dict()
                field_name = f"{ad_type}_Ads"
                
                if field_name in current_data and isinstance(current_data[field_name], list):
                    original_count = len(current_data[field_name])
                    current_data[field_name] = [ad for ad in current_data[field_name] if ad.get('id') != ad_id]
                    
                    if len(current_data[field_name]) != original_count:
                        deleted = True
                        target_doc_id = doc.id
                        
                        # Delete image from Cloudinary for banner and popup ads
                        if ad_type in ['banner', 'popup']:
                            try:
                                # Find the deleted ad to get image URL
                                for ad in current_data[field_name]:
                                    if ad.get('id') == ad_id and 'image_url' in ad:
                                        image_url = ad['image_url']
                                        if 'cloudinary.com' in image_url:
                                            public_id = image_url.split('/')[-1].split('.')[0]
                                            cloudinary.uploader.destroy(public_id)
                                        break
                            except Exception as e:
                                print(f"Warning: Could not delete Cloudinary image: {str(e)}")
                        break
            
            if not deleted:
                return JsonResponse({'success': False, 'error': 'Ad not found'})
            
            # Save updated data
            if target_doc_id:
                ads_ref.document(target_doc_id).set(current_data)
            
            return JsonResponse({'success': True, 'message': f'{ad_type.capitalize()} ad deleted successfully'})
            
        except Exception as e:
            print(f"Debug: Error in delete_ad: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def get_active_ads(request, ad_type):
    """API endpoint to get active ads for mobile app"""
    try:
        ads_ref = db.collection('ads').document('Tj0a1J50TeKUVjmWvg26')
        ads_doc = ads_ref.get()
        
        if not ads_doc.exists:
            return JsonResponse({'success': True, 'ads': []})
        
        current_data = ads_doc.to_dict()
        field_name = f"{ad_type}_Ads"
        
        if field_name not in current_data:
            return JsonResponse({'success': True, 'ads': []})
        
        # Filter active ads
        active_ads = [ad for ad in current_data[field_name] if ad.get('is_active', True)]
        
        return JsonResponse({'success': True, 'ads': active_ads})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
import logging
import datetime  # Add this import
from django.utils.timezone import now  # Better alternative

logger = logging.getLogger(__name__)

def feedback_page(request):
    """Render the feedback page"""
    return render(request, 'feedback.html')

@csrf_exempt
def submit_feedback(request):
    """Handle feedback submission"""
    if request.method == 'POST':
        try:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                # AJAX request
                data = json.loads(request.body)
            else:
                # Form submission
                data = request.POST
            
            # Validate required fields
            if not data.get('rating'):
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Please provide a rating'
                })
            
            # Prepare feedback data
            feedback_data = {
                'name': data.get('name', '').strip(),
                'email': data.get('email', '').strip(),
                'vehicle': data.get('vehicle', ''),
                'rating': int(data.get('rating', 0)),
                'feedback': data.get('feedback', '').strip(),
                'notification_method': data.get('notification_method', ''),
                'timestamp': now()  # Use Django's timezone-aware now()
            }
            
            # Send email
            email_sent = send_feedback_email(feedback_data)
            
            # Also save to Firestore for record keeping
            try:
                feedback_id = str(uuid.uuid4())
                db.collection('feedback').document(feedback_id).set({
                    **feedback_data,
                    'id': feedback_id,
                    'timestamp': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                logger.error(f"Failed to save feedback to Firestore: {str(e)}")
                # Continue even if Firestore save fails
            
            if email_sent:
                return JsonResponse({
                    'status': 'success', 
                    'message': 'Thank you for your feedback! We appreciate your input.'
                })
            else:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Failed to send feedback. Please try again.'
                })
                
        except Exception as e:
            logger.error(f"Error in submit_feedback: {str(e)}")
            return JsonResponse({
                'status': 'error', 
                'message': 'An error occurred. Please try again.'
            })
    
    return JsonResponse({
        'status': 'error', 
        'message': 'Invalid request method'
    })

def send_feedback_email(feedback_data):
    """Send feedback email to admin"""
    subject = f"New Feedback Received - Rating: {feedback_data['rating']}/5"
    
    # Use timezone-aware timestamp
    current_time = now()
    
    html_message = render_to_string('feedback_email.html', {
        'name': feedback_data.get('name', 'Anonymous'),
        'email': feedback_data.get('email', 'Not provided'),
        'vehicle': feedback_data.get('vehicle', 'Not specified'),
        'rating': feedback_data.get('rating', 0),
        'feedback': feedback_data.get('feedback', 'No feedback provided'),
        'timestamp': current_time.strftime("%B %d, %Y at %I:%M:%S %p"),
        'notification_method': feedback_data.get('notification_method', 'Not specified')
    })
    
    plain_message = f"""
    New Feedback Received
    
    Name: {feedback_data.get('name', 'Anonymous')}
    Email: {feedback_data.get('email', 'Not provided')}
    Vehicle: {feedback_data.get('vehicle', 'Not specified')}
    Rating: {feedback_data.get('rating', 0)}/5
    Notification Method: {feedback_data.get('notification_method', 'Not specified')}
    
    Feedback:
    {feedback_data.get('feedback', 'No feedback provided')}
    
    Timestamp: {current_time.strftime("%B %d, %Y at %I:%M:%S %p")}
    """
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[getattr(settings, 'FEEDBACK_EMAIL', 'admin@sudo.com')],  # Safe fallback
            fail_silently=False
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send feedback email: {str(e)}")
        return False

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

def view_feedback(request):
    """View all feedback submissions"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    try:
        # Get all feedback from Firestore
        feedback_ref = db.collection('feedback')
        feedback_docs = feedback_ref.stream()
        
        feedback_list = []
        for doc in feedback_docs:
            feedback_data = doc.to_dict()
            feedback_data['id'] = doc.id
            
            # Convert Firestore timestamp to readable format
            if hasattr(feedback_data.get('timestamp'), 'strftime'):
                feedback_data['timestamp'] = feedback_data['timestamp'].strftime("%B %d, %Y at %I:%M:%S %p")
            elif isinstance(feedback_data.get('timestamp'), str):
                # Already a string
                pass
            else:
                feedback_data['timestamp'] = 'Unknown date'
            
            feedback_list.append(feedback_data)
        
        # Sort by timestamp (newest first)
        feedback_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Calculate statistics
        total_feedback = len(feedback_list)
        average_rating = sum(fb.get('rating', 0) for fb in feedback_list) / total_feedback if total_feedback > 0 else 0
        rating_counts = {i: 0 for i in range(1, 6)}
        for fb in feedback_list:
            rating = fb.get('rating', 0)
            if 1 <= rating <= 5:
                rating_counts[rating] += 1
        
    except Exception as e:
        messages.error(request, f'Error loading feedback: {str(e)}')
        feedback_list = []
        total_feedback = 0
        average_rating = 0
        rating_counts = {i: 0 for i in range(1, 6)}
    
    # Pagination
    page = request.GET.get('page', 1)
    items_per_page = 10
    
    paginator = Paginator(feedback_list, items_per_page)
    
    try:
        feedback_page = paginator.page(page)
    except PageNotAnInteger:
        feedback_page = paginator.page(1)
    except EmptyPage:
        feedback_page = paginator.page(paginator.num_pages)
    
    context = {
        'feedback_list': feedback_page,
        'total_feedback': total_feedback,
        'average_rating': round(average_rating, 1),
        'rating_counts': rating_counts,
        'paginator': paginator,
    }
    
    return render(request, 'view_feedback.html', context)

def delete_feedback(request, feedback_id):
    """Delete a specific feedback entry"""
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    
    try:
        db.collection('feedback').document(feedback_id).delete()
        messages.success(request, 'Feedback deleted successfully')
    except Exception as e:
        messages.error(request, f'Error deleting feedback: {str(e)}')
    
    return redirect('view_feedback')

@csrf_exempt
def bulk_delete_feedback(request):
    """Bulk delete feedback entries"""
    if not request.session.get('admin'):
        return JsonResponse({'success': False, 'error': 'Admin access required'})
    
    if request.method == 'POST':
        try:
            feedback_ids = request.POST.getlist('feedback_ids[]')
            deleted_count = 0
            
            for feedback_id in feedback_ids:
                try:
                    db.collection('feedback').document(feedback_id).delete()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Error deleting feedback {feedback_id}: {str(e)}")
            
            messages.success(request, f'Successfully deleted {deleted_count} feedback entries')
            return JsonResponse({'success': True, 'deleted_count': deleted_count})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


def validate_api_key(request):
    """
    Validate API key from request headers.
    API key should be passed in X-API-Key header or Authorization header.
    Expected API key: SudoTag001
    """
    api_key = 'SudoTag001'
    
    # Try to get API key from various header formats
    provided_key = (
        request.headers.get('X-API-Key') or
        request.headers.get('x-api-key') or
        request.META.get('HTTP_X_API_KEY') or
        request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '').replace('ApiKey ', '') or
        request.GET.get('api_key') or
        ''
    )
    
    # Remove 'Bearer ' or 'ApiKey ' prefix if present
    if provided_key.startswith('Bearer '):
        provided_key = provided_key.replace('Bearer ', '')
    if provided_key.startswith('ApiKey '):
        provided_key = provided_key.replace('ApiKey ', '')
    
    return provided_key == api_key


@csrf_exempt
def call_webhook(request):
    """
    Call webhook API endpoint.
    
    Request:
    - Method: POST
    - Headers: 
      - Content-Type: application/json
      - X-API-Key: SudoTag001 (or Authorization: ApiKey SudoTag001)
    - Body:
      {
        "from": "1234567890",
        "did": "1234567890",
        "to": "9846098460"
      }
    
    Response:
    {
      "status": "1",
      "destination": "9846098460"
    }
    
    All phone numbers must be exactly 10 digits (with or without +91 prefix).
    """
    if request.method != 'POST':
        return JsonResponse({
            'error': 'Method not allowed. Use POST.'
        }, status=405)
    
    # Validate API key
    if not validate_api_key(request):
        return JsonResponse({
            'error': 'Unauthorized. Invalid or missing API key.'
        }, status=401)
    
    # Parse data from multiple sources: JSON body, form data, or query parameters
    body_data = {}
    
    # Priority 1: Check query parameters (for GET/POST with ?from=...&did=...&to=...)
    if request.GET:
        body_data = request.GET.dict()
        print("=" * 50)
        print("Call Webhook API - Received from QUERY PARAMETERS:")
        print("=" * 50)
    
    # Priority 2: Check form data (for POST with form-urlencoded)
    elif request.POST:
        body_data = request.POST.dict()
        print("=" * 50)
        print("Call Webhook API - Received from FORM DATA:")
        print("=" * 50)
    
    # Priority 3: Check JSON body
    elif request.content_type == 'application/json':
        try:
            body_data = json.loads(request.body)
            print("=" * 50)
            print("Call Webhook API - Received from JSON BODY:")
            print("=" * 50)
        except (json.JSONDecodeError, ValueError) as e:
            return JsonResponse({
                'error': 'Invalid JSON format in request body.'
            }, status=400)
    
    # Print/log the received parameters (raw values)
    print(f"from: {body_data.get('from') or body_data.get('from_number', 'Not provided')}")
    print(f"did: {body_data.get('did') or body_data.get('did_number', 'Not provided')}")
    print(f"to: {body_data.get('to') or body_data.get('to_number', 'Not provided')}")
    print("=" * 50)
    
    # Validate request data using serializer
    serializer = CallWebhookSerializer(body_data)
    
    if not serializer.is_valid():
        return JsonResponse({
            'error': 'Validation failed',
            'errors': serializer.errors
        }, status=400)
    
    # Get validated data
    validated_data = serializer.validated_data
    from_number = validated_data.get('from')
    did_number = validated_data.get('did')
    to_number = validated_data.get('to')
    
    # Print the validated/processed numbers
    print("Validated/Processed Numbers:")
    print(f"from: {from_number}")
    print(f"did: {did_number}")
    print(f"to: {to_number}")
    print("=" * 50)
    
    # Return response in the exact format specified
    response_data = {
        'status': '1',
        'destination': to_number
    }
    
    return JsonResponse(response_data, status=200)