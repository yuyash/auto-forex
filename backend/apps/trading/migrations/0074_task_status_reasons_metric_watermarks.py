from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trading", "0073_tradingtask_tick_granularity"),
    ]

    operations = [
        migrations.AddField(
            model_name="backtesttask",
            name="status_reason_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Stable public reason code for the latest stop/failure trigger",
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name="backtesttask",
            name="status_reason_message",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Public message explaining the latest stop/failure trigger",
            ),
        ),
        migrations.AddField(
            model_name="executionmetricaggregate",
            name="watermarks",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Execution watermark values and timestamps keyed by summary metric",
            ),
        ),
        migrations.AddField(
            model_name="tradingtask",
            name="status_reason_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Stable public reason code for the latest stop/failure trigger",
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name="tradingtask",
            name="status_reason_message",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Public message explaining the latest stop/failure trigger",
            ),
        ),
    ]
