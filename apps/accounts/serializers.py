from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "is_staff", "created_at"]
        read_only_fields = fields


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, max_length=128)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)  # length / common-password / all-numeric checks
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(TokenObtainPairSerializer):
    """Email + password in, access + refresh tokens out."""

    def validate(self, attrs):
        attrs[self.username_field] = attrs[self.username_field].strip().lower()
        return super().validate(attrs)


class AuthResponseSerializer(serializers.Serializer):
    """Documents the signup response for the OpenAPI schema."""

    user = UserSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()
