from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User


# ✅ 마이페이지용 사용자 정보 조회 시리얼라이저
class UserDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nickname",
            "profile_image",
            "introduction",
            "date_joined"
        ]
        read_only_fields = ["id", "email", "date_joined"]


# ✅ 사용자 정보 수정용 시리얼라이저
class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["nickname", "profile_image", "introduction"]


# ✅ 비밀번호 변경 시리얼라이저
class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.USERNAME_FIELD

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = {'id': self.user.id, 'email': self.user.email,
                        'nickname': self.user.nickname}
        return data
