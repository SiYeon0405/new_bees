from rest_framework import serializers

from .models import Group


class GroupCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, allow_blank=False, trim_whitespace=True)


class GroupSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ('id', 'name', 'owner_id', 'created_at')


class JoinSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20, allow_blank=False)
