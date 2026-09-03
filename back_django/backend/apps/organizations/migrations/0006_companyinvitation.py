from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("authorization", "0003_initial"),
        ("organizations", "0005_site_site_type_and_more"),
        ("users", "0002_useractiontoken_user_email_verified_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyInvitation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("invited_email", models.EmailField(db_index=True, max_length=254)),
                ("first_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(blank=True, max_length=150)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("accepted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_sent_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("site_ids", models.JSONField(blank=True, default=list)),
                ("zone_ids", models.JSONField(blank=True, default=list)),
                ("accepted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="accepted_company_invitations", to="users.user")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="invitations", to="organizations.company")),
                ("invited_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sent_company_invitation_tokens", to="users.user")),
                ("role", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="company_invitations", to="authorization.companyrole")),
            ],
        ),
        migrations.AddIndex(
            model_name="companyinvitation",
            index=models.Index(fields=["company", "invited_email"], name="organizatio_company_f267af_idx"),
        ),
        migrations.AddIndex(
            model_name="companyinvitation",
            index=models.Index(fields=["company", "created_at"], name="organizatio_company_c516e9_idx"),
        ),
        migrations.AddIndex(
            model_name="companyinvitation",
            index=models.Index(fields=["expires_at"], name="organizatio_expires_210be4_idx"),
        ),
        migrations.AddConstraint(
            model_name="companyinvitation",
            constraint=models.UniqueConstraint(condition=models.Q(("accepted_at__isnull", True), ("cancelled_at__isnull", True)), fields=("company", "invited_email"), name="uniq_active_company_invitation_email"),
        ),
    ]
