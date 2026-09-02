from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("coding", "0005_codingdelegationwatch"), ("orchestration", "0055_durable_chat_delegation_wait")]
    operations = [
        migrations.AlterField(model_name="codingdelegationwatch", name="chat", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="coding_watches", to="chat.chat")),
        migrations.AddField(model_name="codingdelegationwatch", name="call_session", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="coding_watches", to="orchestration.callsession")),
        migrations.AddField(model_name="codingdelegationwatch", name="waiting", field=models.BooleanField(default=False)),
    ]
