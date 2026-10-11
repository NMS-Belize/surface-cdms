from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wx", "0084_alter_raw_data_validated_flag"),
    ]

    operations = [
        # Existing files retain their original AQC/MQC interpretation.
        # These small export-history tables are the only tables altered here.
        migrations.AddField(
            model_name="datafile",
            name="export_mode",
            field=models.CharField(
                max_length=16,
                default="legacy",
                choices=[
                    ("legacy", "Legacy AQC/MQC settings"),
                    ("validated", "Validated data"),
                    ("aqc_good", "Good data - AQC only"),
                    ("all", "All data"),
                    ("summary", "Stored summary"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="combinedatafile",
            name="export_mode",
            field=models.CharField(
                max_length=16,
                default="legacy",
                choices=[
                    ("legacy", "Legacy AQC/MQC settings"),
                    ("validated", "Validated data"),
                    ("aqc_good", "Good data - AQC only"),
                    ("all", "All data"),
                    ("summary", "Stored summary"),
                ],
            ),
        ),
    ]