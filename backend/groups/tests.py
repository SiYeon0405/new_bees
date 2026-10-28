from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import User
from .models import Group, GroupMember, InviteCode


class GroupAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='owner@example.test', nickname='owner', password='Strong-pass-789!')
        self.member = User.objects.create_user(email='member@example.test', nickname='member', password='Strong-pass-789!')
        self.outsider = User.objects.create_user(email='outside@example.test', nickname='outside', password='Strong-pass-789!')
        self.client = APIClient()

    def as_user(self, user):
        self.client.force_authenticate(user=user)

    def test_creation_and_membership_scoped_reads(self):
        self.assertEqual(self.client.get('/api/groups/').status_code, 401)
        self.as_user(self.owner)
        response = self.client.post('/api/groups/', {
            'name': 'Alpha', 'owner_id': self.outsider.id, 'role': 'member'})
        self.assertEqual(response.status_code, 201)
        group_id = response.data['id']
        self.assertEqual(response.data['owner_id'], self.owner.id)
        self.assertTrue(GroupMember.objects.filter(group_id=group_id, user=self.owner, role='owner').exists())
        self.assertEqual(len(self.client.get('/api/groups/').data), 1)
        self.assertEqual(self.client.get(f'/api/groups/{group_id}/').status_code, 200)
        other_group = Group.objects.create(name='Beta', owner=self.outsider)
        GroupMember.objects.create(group=other_group, user=self.outsider, role='owner')
        self.assertEqual(self.client.get(f'/api/groups/{other_group.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/groups/{other_group.id}/invites/').status_code, 404)
        self.as_user(self.outsider)
        self.assertEqual([item['id'] for item in self.client.get('/api/groups/').data], [other_group.id])
        self.assertEqual(self.client.get(f'/api/groups/{group_id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/groups/{group_id}/invites/').status_code, 404)

    def test_invite_join_duplicate_and_member_permissions(self):
        self.as_user(self.owner)
        group_id = self.client.post('/api/groups/', {'name': 'Alpha'}).data['id']
        invite = self.client.post(f'/api/groups/{group_id}/invites/')
        self.assertEqual(invite.status_code, 201)
        code = invite.data['code']
        self.assertEqual(len(code), 20)
        self.assertGreater(InviteCode.objects.get(code=code).expiration_date, timezone.now())
        self.as_user(self.member)
        joined = self.client.post('/api/groups/join/', {
            'code': code, 'user_id': self.outsider.id, 'role': 'owner'})
        self.assertEqual(joined.status_code, 201)
        self.assertEqual(joined.data['role'], 'member')
        self.assertEqual(self.client.get(f'/api/groups/{group_id}/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/groups/{group_id}/invites/').status_code, 403)
        repeated = self.client.post('/api/groups/join/', {'code': code})
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.data['joined'])
        self.assertEqual(GroupMember.objects.filter(group_id=group_id, user=self.member).count(), 1)
        self.assertFalse(GroupMember.objects.filter(group_id=group_id, user=self.outsider).exists())

    def test_invalid_and_expired_code_do_not_disclose_group(self):
        group = Group.objects.create(name='Hidden', owner=self.owner)
        GroupMember.objects.create(group=group, user=self.owner, role='owner')
        expired = InviteCode.objects.create(group=group, code='expired-code',
            expiration_date=timezone.now() - timedelta(seconds=1))
        self.as_user(self.member)
        for code in ('unknown-code', expired.code):
            response = self.client.post('/api/groups/join/', {'code': code})
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('Hidden', str(response.data))
            self.assertNotIn(str(group.id), str(response.data))
        self.assertFalse(GroupMember.objects.filter(group=group, user=self.member).exists())
