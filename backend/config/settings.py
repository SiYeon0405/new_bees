from pathlib import Path
from datetime import timedelta
import pymysql
import os

# 프로젝트 루트 경로
BASE_DIR = Path(__file__).resolve().parent.parent

# 보안
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.getenv('DJANGO_DEBUG', 'false').lower() == 'true'
ALLOWED_HOSTS = [host.strip() for host in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if host.strip()]

# 앱 등록
INSTALLED_APPS = [
    # Django 기본 앱
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 사용자 앱
    'users',
    'groups',
    'files',
    'comments',
    'notifications',
    'ai_assistant',

    # 외부 라이브러리
    'rest_framework',
    'rest_framework_simplejwt',
]

# 사용자 정의 유저 모델
AUTH_USER_MODEL = 'users.User'

# 미들웨어
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# URL 및 WSGI
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

# 템플릿
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'config' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# pymysql을 MySQLdb처럼 사용
pymysql.install_as_MySQLdb()

# 데이터베이스 설정
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('MYSQL_DATABASE', 'bees_dev'),
        'USER': os.getenv('MYSQL_USER', 'bees'),
        'PASSWORD': os.getenv('MYSQL_PASSWORD', ''),
        'HOST': os.getenv('MYSQL_HOST', '127.0.0.1'),
        'PORT': os.getenv('MYSQL_PORT', '3307'),
        'TEST': {'NAME': os.getenv('MYSQL_TEST_DATABASE', 'test_' + os.getenv('MYSQL_DATABASE', 'bees_dev'))},
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
if os.getenv('DJANGO_DB_ENGINE') == 'sqlite':
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.getenv('SQLITE_PATH', str(BASE_DIR / 'db.sqlite3')),
    }

# 비밀번호 검증
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 언어 및 시간
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = False

# 정적 파일
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'config' / 'static']
MEDIA_ROOT = os.getenv('MEDIA_ROOT', str(BASE_DIR / 'private_media'))

# 기본 필드 타입
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework 설정
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

# JWT 토큰 만료 시간 (선택사항)
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

AI_INDEX_ENABLED = os.getenv('AI_INDEX_ENABLED', 'false').lower() == 'true'
AI_AUTO_INDEX_ENABLED = os.getenv('AI_AUTO_INDEX_ENABLED', 'true').lower() == 'true'
AI_APPROVED_GROUP_ID = int(os.getenv('AI_APPROVED_GROUP_ID', '0'))
AI_INDEX_CURRENT_ONLY = os.getenv('AI_INDEX_CURRENT_ONLY', 'false').lower() == 'true'
AI_EMBEDDING_PROVIDER = os.getenv('AI_EMBEDDING_PROVIDER', 'disabled')
AI_EMBEDDING_MODEL = os.getenv('AI_EMBEDDING_MODEL', 'text-embedding-3-small')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
AI_EMBEDDING_DIMENSION = int(os.getenv('AI_EMBEDDING_DIMENSION', '512'))
AI_CHUNK_CHARS = int(os.getenv('AI_CHUNK_CHARS', '1800'))
AI_CHUNK_OVERLAP_CHARS = int(os.getenv('AI_CHUNK_OVERLAP_CHARS', '240'))
AI_MAX_DOCUMENT_CHARS = int(os.getenv('AI_MAX_DOCUMENT_CHARS', '200000'))
AI_INDEX_REVISION = os.getenv('AI_INDEX_REVISION', 'v1')
AI_SPLIT_REVISION = os.getenv('AI_SPLIT_REVISION', 'paragraph-char-v1')
AI_MAX_ATTEMPTS = int(os.getenv('AI_MAX_ATTEMPTS', '3'))
AI_MANUAL_RETRY_ENABLED = os.getenv('AI_MANUAL_RETRY_ENABLED', 'true').lower() == 'true'
AI_MAX_EMBEDDING_INPUT_BYTES = int(os.getenv('AI_MAX_EMBEDDING_INPUT_BYTES', '100000'))
AI_LEASE_SECONDS = int(os.getenv('AI_LEASE_SECONDS', '180'))
QDRANT_URL = os.getenv('QDRANT_URL', 'http://qdrant:6333')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_TASK_DEFAULT_QUEUE = os.getenv('CELERY_TASK_DEFAULT_QUEUE', 'celery')
CELERY_TASK_SOFT_TIME_LIMIT = 120
CELERY_TASK_TIME_LIMIT = 150
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
AI_QA_ENABLED = os.getenv('AI_QA_ENABLED', 'false').lower() == 'true'
AI_QA_TOTAL_QUESTION_LIMIT = int(os.getenv('AI_QA_TOTAL_QUESTION_LIMIT', '0'))
AI_LLM_PROVIDER = os.getenv('AI_LLM_PROVIDER', 'fake')
AI_LLM_EXTERNAL_ENABLED = os.getenv('AI_LLM_EXTERNAL_ENABLED', 'false').lower() == 'true'
AI_LLM_EVAL_MODE = os.getenv('AI_LLM_EVAL_MODE', 'false').lower() == 'true'
AI_LLM_MODEL = os.getenv('AI_LLM_MODEL', 'gpt-4o-mini')
AI_LLM_PROMPT_REVISION = os.getenv('AI_LLM_PROMPT_REVISION', 'grounded-v1')
AI_LLM_TIMEOUT_SECONDS = int(os.getenv('AI_LLM_TIMEOUT_SECONDS', '30'))
AI_LLM_MAX_OUTPUT_TOKENS = int(os.getenv('AI_LLM_MAX_OUTPUT_TOKENS', '400'))
AI_QA_MAX_CONTEXT_CHARS = int(os.getenv('AI_QA_MAX_CONTEXT_CHARS', '6000'))
AI_QA_MAX_ATTEMPTS = int(os.getenv('AI_QA_MAX_ATTEMPTS', '2'))
AI_QA_LEASE_SECONDS = int(os.getenv('AI_QA_LEASE_SECONDS', '120'))
