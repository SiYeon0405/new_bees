from django.shortcuts import get_object_or_404
from groups.models import Group
from .models import File, FileVersion


def member_group(user, group_id):
    return get_object_or_404(Group.objects.filter(members__user=user), pk=group_id)


def group_files(group):
    return File.objects.filter(group=group, deleted_at__isnull=True)


def group_file(group, file_id):
    return get_object_or_404(group_files(group), pk=file_id)


def file_version(file, version_id):
    return get_object_or_404(FileVersion, file=file, pk=version_id)
