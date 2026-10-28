from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

class BrowserAPIAuthentication:
    authentication_classes = (JWTAuthentication, SessionAuthentication)
