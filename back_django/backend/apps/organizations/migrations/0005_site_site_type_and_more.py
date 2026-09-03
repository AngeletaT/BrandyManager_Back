from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0004_company_uniq_company_tax_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="site_type",
            field=models.CharField(
                choices=[
                    ("BRANCH", "Branch"),
                    ("FRANCHISE", "Franchise"),
                    ("STORE", "Store"),
                    ("OFFICE", "Office"),
                    ("OTHER", "Other"),
                ],
                db_index=True,
                default="BRANCH",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="site",
            index=models.Index(fields=["company", "site_type"], name="organizatio_company_d5f6c3_idx"),
        ),
    ]
