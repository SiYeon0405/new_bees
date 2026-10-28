import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from groups.models import Group, GroupMember
from users.models import User
from .models import File, FileVersion
from .services import create_version


def upload(name='note.md', data=b'hello'):
    return SimpleUploadedFile(name, data, content_type='application/octet-stream')


class FileAPITests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_ctx = override_settings(MEDIA_ROOT=self.temp.name)
        self.settings_ctx.enable()
        self.addCleanup(self.settings_ctx.disable)
        self.owner = User.objects.create_user(email='owner@file.test', nickname='owner', password='Strong-pass-789!')
        self.member = User.objects.create_user(email='member@file.test', nickname='member', password='Strong-pass-789!')
        self.outsider = User.objects.create_user(email='outsider@file.test', nickname='outsider', password='Strong-pass-789!')
        self.group = Group.objects.create(name='one', owner=self.owner)
        self.other = Group.objects.create(name='two', owner=self.outsider)
        for group, user in ((self.group, self.owner), (self.group, self.member), (self.other, self.outsider)):
            GroupMember.objects.create(group=group, user=user)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.base = f'/api/groups/{self.group.id}/files/'

    def create(self, name='note.md', data=b'hello'):
        return self.client.post(self.base, {'file': upload(name, data)}, format='multipart')

    def test_upload_read_versions_download_and_delete(self):
        first = self.create()
        self.assertEqual(first.status_code, 201)
        fid = first.data['file']['id']
        vid = first.data['version']['id']
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.client.get(f'{self.base}{fid}/').status_code, 200)
        self.assertEqual(b''.join(self.client.get(f'{self.base}{fid}/versions/{vid}/download/').streaming_content), b'hello')
        second = self.client.post(f'{self.base}{fid}/versions/', {'file': upload('new.txt', b'changed')}, format='multipart')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data['version']['version_number'], 2)
        self.assertEqual(self.client.post(f'{self.base}{fid}/versions/', {'file': upload('new.txt', b'changed')}, format='multipart').status_code, 409)
        self.assertNotEqual(FileVersion.objects.get(pk=vid).uploaded_file.name, FileVersion.objects.get(pk=second.data['version']['id']).uploaded_file.name)
        self.assertEqual(b''.join(self.client.get(f'{self.base}{fid}/versions/{vid}/download/').streaming_content), b'hello')
        self.assertEqual(len(self.client.get(f'{self.base}{fid}/versions/').data), 2)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.delete(f'{self.base}{fid}/').status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(f'{self.base}{fid}/').status_code, 204)
        for path in (self.base + str(fid) + '/', self.base + str(fid) + '/versions/', self.base + str(fid) + f'/versions/{vid}/download/'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(self.base).data, [])

    def test_group_isolation_ids_and_departure(self):
        fid = self.create().data['file']['id']
        vid = FileVersion.objects.get(file_id=fid).id
        other_base = f'/api/groups/{self.other.id}/files/'
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(other_base).status_code, 200)
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.assertEqual(self.client.get(f'{other_base}{fid}/').status_code, 404)
        self.assertEqual(self.client.get(f'{other_base}{fid}/versions/{vid}/download/').status_code, 404)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        GroupMember.objects.filter(group=self.group, user=self.member).delete()
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.assertEqual(self.client.get(f'{self.base}{fid}/versions/{vid}/download/').status_code, 404)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.base).status_code, 401)

    def test_same_name_separate_documents_and_invalid_inputs(self):
        self.assertNotEqual(self.create().data['file']['id'], self.create().data['file']['id'])
        for name, data in [('empty.txt', b''), ('bad.md', b'\xff'), ('bad.pdf', b'hello'), ('too.txt', b'a' * (5 * 1024 * 1024 + 1))]:
            self.assertEqual(self.create(name, data).status_code, 400)
        from io import BytesIO
        unsafe = BytesIO(b'ok')
        unsafe.name = '../bad.txt'
        unsafe.size = 2
        from .services import validated_upload
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            validated_upload(unsafe)
        self.assertEqual(File.objects.count(), 2)

    def test_database_failure_cleans_stored_file(self):
        with patch('files.services.FileVersion.objects.create', side_effect=RuntimeError('db failure')):
            with self.assertRaises(RuntimeError):
                create_version(self.group, self.owner, upload())
        self.assertEqual(File.objects.count(), 0)
        self.assertFalse(any(files for _, _, files in os.walk(self.temp.name)))

    def test_storage_failure_rolls_back_database(self):
        with patch('files.services.FileVersion._meta.get_field') as field:
            field.return_value.storage.save.side_effect = OSError('storage failure')
            with self.assertRaises(OSError):
                create_version(self.group, self.owner, upload())
        self.assertEqual(File.objects.count(), 0)

    def test_same_filename_in_other_group_and_owner_delete(self):
        own_id = self.create().data['file']['id']
        own_version = FileVersion.objects.get(file_id=own_id).id
        second_id = self.create('other.md').data['file']['id']
        self.assertEqual(self.client.get(f'{self.base}{second_id}/versions/{own_version}/download/').status_code, 404)
        self.client.force_authenticate(self.outsider)
        other_id = self.client.post(f'/api/groups/{self.other.id}/files/', {'file': upload()}, format='multipart').data['file']['id']
        self.assertNotEqual(own_id, other_id)
        self.assertEqual(self.client.get(f'{self.base}{other_id}/').status_code, 404)
        self.client.force_authenticate(self.member)
        member_id = self.create('member.txt').data['file']['id']
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(f'{self.base}{member_id}/').status_code, 204)


@override_settings(AI_INDEX_ENABLED=False)
class ConcurrentVersionTests(TransactionTestCase):
    def test_mysql_separate_connections_allocate_unique_versions(self):
        from django.db import connection
        if connection.vendor != 'mysql':
            self.skipTest('MySQL row locking required')
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                user = User.objects.create_user(email='race@file.test', nickname='race', password='Strong-pass-789!')
                group = Group.objects.create(name='race', owner=user)
                document, first = create_version(group, user, upload())
                def worker(index):
                    close_old_connections()
                    try:
                        from django.db import connection as thread_connection
                        with thread_connection.cursor() as cursor:
                            cursor.execute('SELECT CONNECTION_ID()')
                            connection_id = cursor.fetchone()[0]
                        _, version = create_version(group, user, upload('race.md', f'part {index}'.encode()), document)
                        return connection_id, version.version_number, version.uploaded_file.name
                    finally:
                        close_old_connections()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(worker, (1, 2)))
                self.assertEqual(sorted(row[1] for row in results), [2, 3])
                self.assertEqual(len({row[0] for row in results}), 2)
                self.assertEqual(len({row[2] for row in results}), 2)
                self.assertEqual(File.objects.get(pk=document.pk).current_version_number, 3)
                self.assertTrue(first.uploaded_file.storage.exists(first.uploaded_file.name))
