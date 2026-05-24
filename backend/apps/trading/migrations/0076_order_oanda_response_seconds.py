"""Add OANDA order response latency to order records."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trading", "0075_alter_tradingtask_live_tick_stale_guard_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="oanda_response_seconds",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text=(
                    "Elapsed wall-clock seconds from submitting the OANDA order "
                    "request until the response/error returned."
                ),
                max_digits=12,
                null=True,
            ),
        ),
    ]
