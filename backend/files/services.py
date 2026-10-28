import hashlib
import uuid
from pathlib import PurePath

from django.core.files.base import ContentFile
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.exceptions import APIException

from .models import File, FileVersion

MAX_SIZE = 5 * 1024 * 1024

class DuplicateVersion(APIException):
    status_code = 409
    default_detail = 'The current version already has identical content.'


def validated_upload(upload):
    if upload is None:
        raise ValidationError({'file': 'File is required.'})
    name = upload.name
    if not name or name != PurePath(name).name or '/' in name or '\\' in name or '..' in name or len(name) > 255:
        raise ValidationError({'file': 'Invalid filename.'})
    suffix = PurePath(name).suffix.lower()
    if suffix not in ('.txt', '.md', '.markdown'):
        raise ValidationError({'file': 'Only TXT and Markdown are supported.'})
    if upload.size > MAX_SIZE:
        raise ValidationError({'file': 'File exceeds 5 MB.'})
    data = upload.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise ValidationError({'file': 'File exceeds 5 MB.'})
    if not data:
        raise ValidationError({'file': 'File is empty.'})
    try:
        data.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise ValidationError({'file': 'UTF-8 text is required.'})
    if b'\x00' in data:
        raise ValidationError({'file': 'NUL bytes are not supported.'})
    mime = 'text/markdown' if suffix in ('.md', '.markdown') else 'text/plain'
    return name, data, mime


def create_version(group, user, upload, existing=None):
    name, data, mime = validated_upload(upload)
    storage = FileVersion._meta.get_field('uploaded_file').storage
    stored_name = None
    try:
        with transaction.atomic():
            if existing is None:
                document = File.objects.create(group=group, name=name, created_by=user)
                number = 1
            else:
                document = File.objects.select_for_update().get(pk=existing.pk, group=group, deleted_at__isnull=True)
                current = document.versions.filter(version_number=document.current_version_number).first()
                if current and current.sha256 == hashlib.sha256(data).hexdigest():
                    raise DuplicateVersion()
                number = (document.current_version_number or document.versions.order_by('-version_number').values_list('version_number', flat=True).first() or 0) + 1
            stored_name = storage.save(f'uploads/{uuid.uuid4().hex}', ContentFile(data))
            version = FileVersion.objects.create(file=document, version_number=number, uploaded_file=stored_name,
                uploaded_by=user, original_name=name, size=len(data), mime_type=mime, sha256=hashlib.sha256(data).hexdigest())
            document.current_version_number = number
            document.save(update_fields=['current_version_number'])
            from ai_assistant.services import queue_version
            if settings.AI_AUTO_INDEX_ENABLED:
                queue_version(version)
        return document, version
    except Exception:
        if stored_name:
            storage.delete(stored_name)
        raise


def delete_file(document):
    with transaction.atomic():
        locked = File.objects.select_for_update().get(pk=document.pk, deleted_at__isnull=True)
        locked.deleted_at = timezone.now()
        locked.save(update_fields=['deleted_at'])
        from ai_assistant.models import ActiveIndex
        ActiveIndex.objects.filter(file=locked).delete()
