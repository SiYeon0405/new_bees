from .models import Group


def member_groups(user):
    return Group.objects.filter(members__user=user).select_related('owner').distinct()
