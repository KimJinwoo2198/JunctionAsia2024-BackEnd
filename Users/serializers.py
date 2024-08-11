from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import CustomUser
from .exceptions import InvalidCredentialsException, AccountInactiveException
from django.utils.translation import gettext_lazy as _
import re
    
class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, 
        required=True,
        style={'input_type': 'password'},
        help_text='비밀번호는 최소 8자 이상이어야 하며, 숫자와 특수문자를 포함해야 합니다.'
    )
    password2 = serializers.CharField(
        write_only=True, 
        required=True,
        style={'input_type': 'password'},
        help_text='비밀번호 확인을 위해 다시 입력해주세요.'
    )
    email = serializers.EmailField(
        required=True,
        help_text='유효한 이메일 주소를 입력해주세요. 인증 코드가 이 주소로 전송됩니다.'
    )
    phone_number = serializers.CharField(
        required=True,
        help_text='유효한 전화번호를 입력해주세요. 예: 010-1234-5678'
    )
    promotion_agreement = serializers.BooleanField(
        required=False,
        default=False,
        help_text='프로모션 정보 수신에 동의하시면 True로 설정해주세요.'
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password', 'password2', 'phone_number', 'promotion_agreement']

    def validate_username(self, value):
        if CustomUser.objects.filter(username=value).exists():
            raise serializers.ValidationError("이미 사용 중인 사용자 이름입니다.")
        return value

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("이미 등록된 이메일 주소입니다.")
        return value

    def validate_phone_number(self, value):
        import re
        if not re.match(r'^\d{3}-\d{3,4}-\d{4}$', value):
            raise serializers.ValidationError("올바른 전화번호 형식이 아닙니다. 예: 010-1234-5678")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "비밀번호가 일치하지 않습니다."})
        
        try:
            validate_password(attrs['password'])
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})

        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = CustomUser.objects.create_user(**validated_data)
        user.is_active = False
        user.save()
        return user

class CustomAuthTokenSerializer(serializers.Serializer):
    username = serializers.CharField(label=_("Username"), write_only=True)
    password = serializers.CharField(label=_("Password"), style={'input_type': 'password'}, trim_whitespace=False, write_only=True)

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        if username and password:
            user = authenticate(request=self.context.get('request'), username=username, password=password)

            if not user:
                raise InvalidCredentialsException()
            if not user.is_active:
                raise AccountInactiveException()
        else:
            msg = _('Must include "username" and "password".')
            raise serializers.ValidationError(msg, code='authorization')

        attrs['user'] = user
        return attrs

class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("비밀번호는 최소 8자 이상이어야 합니다.")
        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError("비밀번호는 최소 하나의 대문자를 포함해야 합니다.")
        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError("비밀번호는 최소 하나의 소문자를 포함해야 합니다.")
        if not re.search(r'\d', value):
            raise serializers.ValidationError("비밀번호는 최소 하나의 숫자를 포함해야 합니다.")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise serializers.ValidationError("비밀번호는 최소 하나의 특수문자를 포함해야 합니다.")
        return value
    
class CallbackUserInfoSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, help_text="Authorization code from Google")
    
class Enable2FASerializer(serializers.Serializer):
    pass

class Verify2FASerializer(serializers.Serializer):
    username = serializers.CharField()
    token = serializers.CharField(max_length=6)