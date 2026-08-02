from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.users.models import User


class UserDetailSerializer(serializers.ModelSerializer):
    email_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "email_verified",
            "created_at",
        ]
        read_only_fields = fields

    def get_email_verified(self, obj):
        return bool(obj.email_verified_at)


class UserRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_email(self, value):
        return value.strip().lower()


class UserRegisterResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    email = serializers.EmailField()
    next_step = serializers.CharField()


class EmailVerificationResendSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class EmailVerificationResendResponseSerializer(serializers.Serializer):
    status = serializers.CharField()


class EmailVerificationConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(trim_whitespace=False)


class EmailVerificationConfirmResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    next_step = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class PasswordResetRequestResponseSerializer(serializers.Serializer):
    status = serializers.CharField()


class PasswordResetValidateSerializer(serializers.Serializer):
    token = serializers.CharField(trim_whitespace=False)


class PasswordResetValidateResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(trim_whitespace=False)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirmation = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirmation"]:
            raise serializers.ValidationError({"password_confirmation": ["Las contrasenas no coinciden."]})
        return attrs


class PasswordResetConfirmResponseSerializer(serializers.Serializer):
    status = serializers.CharField()


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        return value.strip().lower()


class SessionUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    email_verified = serializers.BooleanField()


class SessionCompanySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    legal_name = serializers.CharField()
    trade_name = serializers.CharField()
    status = serializers.CharField()


class SessionMembershipSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()


class SessionCompanyRoleSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class SessionSubscriptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    plan_code = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    trial_ends_at = serializers.DateTimeField(allow_null=True)
    effective_limits = serializers.DictField()
    functional_access = serializers.BooleanField()
    block_reason = serializers.CharField(allow_null=True)


class SessionContextSerializer(serializers.Serializer):
    access_type = serializers.ChoiceField(choices=["internal_admin", "client_pending", "client"])
    onboarding_required = serializers.BooleanField()
    company = SessionCompanySerializer(allow_null=True)
    membership = SessionMembershipSerializer(allow_null=True)
    company_role = SessionCompanyRoleSerializer(allow_null=True)
    subscription = SessionSubscriptionSerializer(allow_null=True)
    functional_access = serializers.BooleanField()
    block_reason = serializers.CharField(allow_null=True)
    next_step = serializers.CharField()


class SessionResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = SessionUserSerializer()
    context = SessionContextSerializer()


class CurrentUserResponseSerializer(serializers.Serializer):
    user = SessionUserSerializer()
    context = SessionContextSerializer()
