from django.test import TestCase
from rest_framework.test import APIClient
from .models import User


class AuthenticationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup = '/api/users/signup/'
        self.login = '/api/auth/login/'

    def test_signup_login_refresh_and_profile_contract(self):
        response = self.client.post(self.signup, {
            'email': 'member@example.test', 'nickname': '벌',
            'password': 'A-long-test-password-789!'})
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='member@example.test')
        self.assertTrue(user.check_password('A-long-test-password-789!'))
        self.assertEqual(self.client.post(self.signup, {
            'email': user.email, 'nickname': '다른벌',
            'password': 'A-long-test-password-789!'}).status_code, 400)
        self.assertEqual(self.client.get('/api/users/mypage/').status_code, 401)
        login = self.client.post(self.login, {
            'email': user.email, 'password': 'A-long-test-password-789!'})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data['user'], {
            'id': user.id, 'email': user.email, 'nickname': '벌'})
        self.assertNotIn('password', str(login.data))
        self.assertIn('access', login.data)
        refresh = self.client.post('/api/auth/refresh/', {'refresh': login.data['refresh']})
        self.assertEqual(refresh.status_code, 200)
        self.assertIn('access', refresh.data)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + refresh.data['access'])
        profile = self.client.get('/api/users/mypage/')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data['nickname'], '벌')
        self.assertNotIn('password', str(profile.data))

    def test_invalid_and_inactive_login_rejected(self):
        user = User.objects.create_user(email='member@example.test',
                                        nickname='벌', password='A-long-test-password-789!')
        self.assertEqual(self.client.post(self.login, {
            'email': user.email, 'password': 'wrong'}).status_code, 401)
        user.is_active = False
        user.save(update_fields=['is_active'])
        self.assertEqual(self.client.post(self.login, {
            'email': user.email, 'password': 'A-long-test-password-789!'}).status_code, 401)

    def test_weak_password_rejected(self):
        self.assertEqual(self.client.post(self.signup, {
            'email': 'weak@example.test', 'nickname': '벌', 'password': '1234'}).status_code, 400)
