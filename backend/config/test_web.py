import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from groups.models import Group, GroupMember
from users.models import User


class WebFlowTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        setting = override_settings(MEDIA_ROOT=self.media.name)
        setting.enable()
        self.addCleanup(setting.disable)
        self.client = Client(enforce_csrf_checks=True)

    def token(self):
        return self.client.cookies['csrftoken'].value

    def post(self, path, data):
        return self.client.post(path, data, HTTP_X_CSRFTOKEN=self.token())

    def test_signup_login_logout_and_protected_page(self):
        self.assertEqual(self.client.get('/web/').status_code, 302)
        self.client.get('/web/signup/')
        response = self.post('/web/signup/', {'email': 'web@example.test', 'nickname': '웹회원', 'password': 'Strong-pass-789!'})
        self.assertRedirects(response, '/web/', fetch_redirect_response=False)
        self.assertIn('sessionid', self.client.cookies)
        self.assertContains(self.client.get('/web/'), '웹회원')
        self.assertEqual(self.client.post('/web/logout/').status_code, 403)
        self.assertRedirects(self.post('/web/logout/', {}), '/web/login/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/web/').status_code, 302)
        self.assertEqual(self.client.cookies['sessionid'].value, '')
        self.client.get('/web/login/')
        self.assertRedirects(self.post('/web/login/', {'email': 'web@example.test', 'password': 'Strong-pass-789!'}), '/web/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/web/').status_code, 200)

    def test_session_api_csrf_jwt_contract_and_group_file_flow(self):
        owner = User.objects.create_user(email='owner@web.test', nickname='owner', password='Strong-pass-789!')
        second = User.objects.create_user(email='second@web.test', nickname='second', password='Strong-pass-789!')
        self.assertEqual(self.client.get('/api/groups/').status_code, 401)
        self.client.get('/web/login/')
        self.post('/web/login/', {'email': owner.email, 'password': 'Strong-pass-789!'})
        self.assertEqual(self.client.post('/api/groups/', {'name': 'Team'}).status_code, 403)
        group_response = self.post('/api/groups/', {'name': 'Team'})
        self.assertEqual(group_response.status_code, 201)
        group_id = group_response.json()['id']
        self.assertEqual(self.client.get('/api/groups/').json()[0]['id'], group_id)
        self.assertEqual(self.client.get(f'/web/groups/{group_id}/').status_code, 200)
        invite = self.post(f'/api/groups/{group_id}/invites/', {}).json()['code']
        base = f'/api/groups/{group_id}/files/'
        first = self.post(base, {'file': SimpleUploadedFile('one.md', b'first')}).json()
        file_id = first['file']['id']
        first_version = first['version']['id']
        second_version = self.post(f'{base}{file_id}/versions/', {'file': SimpleUploadedFile('two.md', b'second')}).json()['version']['id']
        self.assertEqual(b''.join(self.client.get(f'{base}{file_id}/versions/{first_version}/download/').streaming_content), b'first')
        self.assertEqual(self.client.get(f'/web/groups/{group_id}/files/{file_id}/').status_code, 200)
        other_group = Group.objects.create(name='Other', owner=second)
        GroupMember.objects.create(group=other_group, user=second, role='owner')
        self.assertEqual(self.client.get(f'/api/groups/{other_group.id}/files/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/groups/{other_group.id}/files/{file_id}/versions/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/groups/{other_group.id}/files/{file_id}/versions/{first_version}/download/').status_code, 404)
        self.post('/web/logout/', {})
        self.client.get('/web/login/')
        self.post('/web/login/', {'email': second.email, 'password': 'Strong-pass-789!'})
        self.assertEqual(self.post('/api/groups/join/', {'code': invite}).status_code, 201)
        self.assertEqual(self.client.get(f'{base}{file_id}/').status_code, 200)
        self.assertEqual(self.client.delete(f'{base}{file_id}/', HTTP_X_CSRFTOKEN=self.token()).status_code, 403)
        self.post('/web/logout/', {})
        self.client.get('/web/login/')
        self.post('/web/login/', {'email': owner.email, 'password': 'Strong-pass-789!'})
        self.assertEqual(self.client.delete(f'{base}{file_id}/', HTTP_X_CSRFTOKEN=self.token()).status_code, 204)
        self.assertEqual(self.client.get(f'{base}{file_id}/versions/{second_version}/download/').status_code, 404)
        self.post('/web/logout/', {})
        self.assertEqual(self.client.get(base).status_code, 401)

    def test_jwt_and_template_escaping(self):
        user = User.objects.create_user(email='escape@web.test', nickname='<script>alert(1)</script>', password='Strong-pass-789!')
        self.client.get('/web/login/')
        self.assertEqual(self.client.post('/web/login/', {'email': user.email, 'password': 'Strong-pass-789!'}).status_code, 403)
        self.post('/web/login/', {'email': user.email, 'password': 'Strong-pass-789!'})
        html = self.client.get('/web/').content.decode()
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.post('/web/logout/', {})
        response = self.client.post('/api/auth/login/', {'email': user.email, 'password': 'Strong-pass-789!'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        access = response.json()['access']
        self.assertEqual(self.client.get('/api/groups/', HTTP_AUTHORIZATION=f'Bearer {access}').status_code, 200)
        self.assertEqual(self.client.get('/api/groups/').status_code, 401)
