from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User

def register_user(email, nickname, password):
    if not email or not nickname or not password:
        return None, {'error': '모든 항목을 입력해주세요.'}
    if User.objects.filter(email=email).exists():
        return None, {'error': '이미 존재하는 이메일입니다.'}
    if User.objects.filter(nickname=nickname).exists():
        return None, {'error': '이미 존재하는 닉네임입니다.'}
    try:
        validate_password(password, User(email=email, nickname=nickname))
    except ValidationError as exc:
        return None, {'error': exc.messages}
    return User.objects.create_user(email=email, password=password, nickname=nickname), None
