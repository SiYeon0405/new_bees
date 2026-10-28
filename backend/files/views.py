from django.http import FileResponse, Http404
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from config.authentication import BrowserAPIAuthentication

from .selectors import member_group, group_files, group_file, file_version
from .serializers import FileSerializer, VersionSerializer
from .services import create_version, delete_file

class GroupFilesView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def get(self, request, group_id):
        group = member_group(request.user, group_id)
        return Response(FileSerializer(group_files(group).order_by('-id'), many=True).data)

    def post(self, request, group_id):
        group = member_group(request.user, group_id)
        document, version = create_version(group, request.user, request.FILES.get('file'))
        from ai_assistant.views import status_data
        return Response({'file': FileSerializer(document).data, 'version': VersionSerializer(version).data,
                         'ai_index': status_data(document, version)}, status=201)

class GroupFileView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, file_id):
        group = member_group(request.user, group_id)
        return Response(FileSerializer(group_file(group, file_id)).data)

    def delete(self, request, group_id, file_id):
        group = member_group(request.user, group_id)
        document = group_file(group, file_id)
        if document.created_by_id != request.user.id and group.owner_id != request.user.id:
            return Response({'detail': 'Only the first uploader or group owner may delete this file.'}, status=403)
        delete_file(document)
        return Response(status=204)

class FileVersionsView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def get(self, request, group_id, file_id):
        group = member_group(request.user, group_id)
        document = group_file(group, file_id)
        return Response(VersionSerializer(document.versions.order_by('version_number'), many=True).data)

    def post(self, request, group_id, file_id):
        group = member_group(request.user, group_id)
        document = group_file(group, file_id)
        document, version = create_version(group, request.user, request.FILES.get('file'), document)
        from ai_assistant.views import status_data
        return Response({'file': FileSerializer(document).data, 'version': VersionSerializer(version).data,
                         'ai_index': status_data(document, version)}, status=201)

class VersionDownloadView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id, file_id, version_id):
        group = member_group(request.user, group_id)
        document = group_file(group, file_id)
        version = file_version(document, version_id)
        try:
            stream = version.uploaded_file.open('rb')
        except (OSError, ValueError, FileNotFoundError):
            raise Http404
        response = FileResponse(stream, as_attachment=True, filename=version.original_name or document.name,
                                content_type=version.mime_type or 'application/octet-stream')
        response['X-Content-Type-Options'] = 'nosniff'
        return response
