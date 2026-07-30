import uuid

from django.core.exceptions import ValidationError
from django.db import models


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not kwargs.pop("skip_validation", False):
            self.full_clean()
        return super().save(*args, **kwargs)


class UUIDModel(ValidatedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedUUIDModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


def validate_same_company(*pairs):
    company = None

    for label, value in pairs:
        if value is None:
            continue

        value_company = getattr(value, "company", None)
        if value_company is None and hasattr(value, "site"):
            value_company = getattr(value.site, "company", None)
        if value_company is None and hasattr(value, "zone"):
            value_company = getattr(value.zone, "company", None)

        if value_company is None:
            continue

        if company is None:
            company = value_company
            continue

        if value_company_id(value_company) != value_company_id(company):
            raise ValidationError({label: "El recurso pertenece a otra empresa."})


def value_company_id(company):
    return getattr(company, "id", company)


def validate_date_range(*, starts_at=None, ends_at=None, start_field="starts_at", end_field="ends_at"):
    if starts_at and ends_at and ends_at <= starts_at:
        raise ValidationError({end_field: f"Debe ser posterior a {start_field}."})
