from rest_framework import serializers
from .models import File, FileVersion

class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileVersion
        fields = ('id', 'version_number', 'uploaded_at', 'uploaded_by', 'original_name', 'size', 'mime_type', 'sha256')

class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ('id', 'group', 'name', 'created_by', 'current_version_number', 'uploaded_at')
