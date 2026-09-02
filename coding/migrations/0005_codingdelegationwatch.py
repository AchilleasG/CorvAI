import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("chat", "0005_chat_archived"), ("coding", "0004_managedfile_delegation")]
    operations = [
        migrations.CreateModel(
            name="CodingDelegationWatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("last_event", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("chat", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coding_watches", to="chat.chat")),
                ("delegation", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="chat_watches", to="coding.featuredelegation")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_watches", to="coding.codingsession")),
                ("turn", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="chat_watches", to="coding.codingturn")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="codingdelegationwatch", index=models.Index(fields=["active", "session"], name="coding_watch_active_session")),
    ]
