import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Group, GroupMember, InviteCode


@transaction.atomic
def create_group(*, owner, name):
    group = Group.objects.create(owner=owner, name=name)
    GroupMember.objects.create(group=group, user=owner, role='owner')
    return group


def create_invite(*, group):
    for _ in range(5):
        try:
            return InviteCode.objects.create(
                group=group, code=secrets.token_urlsafe(15),
                expiration_date=timezone.now() + timedelta(hours=24))
        except IntegrityError:
            continue
    raise RuntimeError('Could not generate a unique invite code')


@transaction.atomic
def join_group(*, user, code):
    invite = InviteCode.objects.select_related('group').filter(
        code=code, expiration_date__gt=timezone.now()).first()
    if invite is None:
        return None, False
    try:
        with transaction.atomic():
            membership, created = GroupMember.objects.get_or_create(
                group=invite.group, user=user, defaults={'role': 'member'})
    except IntegrityError:
        membership = GroupMember.objects.get(group=invite.group, user=user)
        created = False
    return membership, created
