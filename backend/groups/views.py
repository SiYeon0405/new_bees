from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from config.authentication import BrowserAPIAuthentication

from .selectors import member_groups
from .serializers import GroupCreateSerializer, GroupSerializer, JoinSerializer
from .services import create_group, create_invite, join_group


class GroupListCreateView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(GroupSerializer(member_groups(request.user), many=True).data)

    def post(self, request):
        serializer = GroupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = create_group(owner=request.user, **serializer.validated_data)
        return Response(GroupSerializer(group).data, status=status.HTTP_201_CREATED)


class GroupDetailView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = get_object_or_404(member_groups(request.user), pk=group_id)
        return Response(GroupSerializer(group).data)


class InviteCreateView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        group = get_object_or_404(member_groups(request.user), pk=group_id)
        if group.owner_id != request.user.id or not group.members.filter(
                user=request.user, role='owner').exists():
            return Response(status=status.HTTP_403_FORBIDDEN)
        invite = create_invite(group=group)
        return Response({'code': invite.code, 'expires_at': invite.expiration_date},
                        status=status.HTTP_201_CREATED)


class GroupJoinView(BrowserAPIAuthentication, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = JoinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership, created = join_group(user=request.user,
                                         code=serializer.validated_data['code'])
        if membership is None:
            return Response({'detail': '유효하지 않은 초대 코드입니다.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({'group_id': membership.group_id, 'role': membership.role,
                         'joined': created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
