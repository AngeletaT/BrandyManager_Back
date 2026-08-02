from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from apps.organizations.normalization import normalize_country_code, normalize_tax_id


ESTIMATED_SITE_CHOICES = ("1", "2-5", "6-10", "11-25", "26-50", "50+")


class OnboardingCompleteSerializer(serializers.Serializer):
    legal_name = serializers.CharField(max_length=255)
    trade_name = serializers.CharField(max_length=255)
    tax_id = serializers.CharField(max_length=64)
    billing_email = serializers.EmailField()
    contact_email = serializers.EmailField()
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    country_code = serializers.CharField(max_length=2)
    default_timezone = serializers.CharField(max_length=64)
    default_language = serializers.CharField(max_length=10)
    sector = serializers.RegexField(regex=r"^[a-z0-9_-]+$", max_length=80)
    estimated_sites = serializers.ChoiceField(choices=ESTIMATED_SITE_CHOICES)

    def validate_tax_id(self, value):
        tax_id = normalize_tax_id(value)
        if not tax_id:
            raise serializers.ValidationError("El identificador fiscal es obligatorio.")
        return tax_id

    def validate_country_code(self, value):
        country_code = normalize_country_code(value)
        if len(country_code) != 2:
            raise serializers.ValidationError("El codigo de pais debe tener dos caracteres.")
        return country_code

    def validate_default_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("La zona horaria no es valida.") from exc
        return value

    def validate_default_language(self, value):
        return value.strip().lower()


class OnboardingCompanySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    legal_name = serializers.CharField()
    trade_name = serializers.CharField()
    tax_id = serializers.CharField()
    status = serializers.CharField()


class OnboardingMembershipSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()


class OnboardingCompanyRoleSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class OnboardingSubscriptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    plan_code = serializers.CharField()
    status = serializers.CharField()
    trial_started_at = serializers.DateTimeField()
    trial_ends_at = serializers.DateTimeField()
    effective_limits = serializers.DictField()
    functional_access = serializers.BooleanField()
    block_reason = serializers.CharField(allow_null=True)


class OnboardingCompleteResponseSerializer(serializers.Serializer):
    company = OnboardingCompanySerializer()
    membership = OnboardingMembershipSerializer()
    company_role = OnboardingCompanyRoleSerializer()
    subscription = OnboardingSubscriptionSerializer()
    next_step = serializers.CharField()
