from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0008_usageevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="usageevent",
            name="prompt_cost",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="usageevent",
            name="completion_cost",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="usageevent",
            name="total_cost",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=12),
        ),
    ]
