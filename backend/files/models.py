from django.db import models
from groups.models import Group
from django.conf import settings

class File(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="files")
    name = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    current_version_number = models.PositiveIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

class FileVersion(models.Model):
    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="versions")
    version_number = models.IntegerField()
    uploaded_file = models.FileField(upload_to="uploads/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    original_name = models.CharField(max_length=255, null=True, blank=True)
    size = models.PositiveIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, null=True, blank=True)
    sha256 = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['file', 'version_number'], name='unique_file_version_number')]

