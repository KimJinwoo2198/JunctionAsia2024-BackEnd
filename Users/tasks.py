import threading
import requests
from .models import CustomUser
from django.core.mail import send_mail
from django.conf import settings
import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from pymongo import MongoClient

client = MongoClient(settings.MONGODB_URI)
db = client[settings.MONGODB_NAME]
user_collection = db['users']
logger = logging.getLogger(__name__)

def run_in_background(func):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.start()
    return wrapper

@run_in_background
def send_verification_email(email, verification_code):
    subject = '[ 00000 ] 이메일 인증을 완료해주세요.'
    message = f'인증 코드: {verification_code}'
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [email]

    # HTML 이메일 템플릿 컨텍스트
    context = {
        'verification_code': verification_code,
    }

    # HTML 이메일 내용 렌더링
    html_content = render_to_string('verification_email.html', context)
    
    # 텍스트 버전 생성
    text_content = strip_tags(html_content)

    # 이메일 메시지 생성
    msg = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    msg.attach_alternative(html_content, "text/html")

    # 이메일 전송
    msg.send(fail_silently=False)

@run_in_background
def get_location_from_ip(ip):
    response = requests.get(f'http://ip-api.com/json/{ip}')
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'fail':
            print(f"Error: {data['message']}")
            return "Unknown Location"
        return f"{data['city']}, {data['country']}"
    return "Unknown Location"

@run_in_background
def save_user_to_mongodb(user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
        user_collection.insert_one({
            'user_name': user.username,
            'user_id': str(user.unique_id),
            'email': user.email,
            'phone_number': user.phone_number,
            'promotion_agreement': user.promotion_agreement
        })
        
        logger.info(f"User data saved to MongoDB for user_id: {user_id}")
    except Exception as e:
        logger.error(f"Failed to save user data to MongoDB for user_id {user_id}: {str(e)}")
        raise

@run_in_background
def send_security_alert(email, username, login_location, login_time, device_info):
    subject = '새 위치에서의 로그인 알림'
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [email]

    # HTML 이메일 템플릿 컨텍스트
    context = {
        'username': username,
        'login_location': login_location,
        'login_time': login_time,
        'device_info': device_info,
        'account_security_link': 'https://yourdomain.com/account/security/'
    }

    # HTML 이메일 내용 렌더링
    html_content = render_to_string('security_alert_email.html', context)
    
    # 텍스트 버전 생성
    text_content = strip_tags(html_content)

    # 이메일 메시지 생성
    msg = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    msg.attach_alternative(html_content, "text/html")

    # 이메일 전송
    msg.send(fail_silently=False)