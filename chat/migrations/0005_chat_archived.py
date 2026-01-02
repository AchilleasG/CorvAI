from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0004_chatmessage_audience_chatmessage_call_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="archived",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
