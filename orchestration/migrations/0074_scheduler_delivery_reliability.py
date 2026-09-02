from django.db import migrations, models

SCHEDULER_GUIDANCE = " In normal conversation, use scheduled_tasks.create_task to arrange future work. When a due scheduled task is executing, its due time has already arrived: perform the requested action immediately and do not recursively schedule or postpone it. For reminders, notifications, or instructions to tell the user something, call messages.send_message during that run; a scheduler summary or log does not reach the user. Only create another scheduled task when the due task explicitly asks for a separate future schedule."
MESSAGE_GUIDANCE = " When a due scheduled task asks for a reminder, notification, or message, call messages.send_message immediately. Creating another scheduled task is not delivery. The inbox message also attempts push delivery."

def configure(apps,schema_editor):
    Module=apps.get_model("orchestration","ToolModule"); Function=apps.get_model("orchestration","ToolFunction")
    scheduled=Module.objects.get(slug="scheduled_tasks")
    if SCHEDULER_GUIDANCE.strip() not in scheduled.caller_instructions:
        scheduled.caller_instructions=scheduled.caller_instructions.rstrip()+SCHEDULER_GUIDANCE
        scheduled.save(update_fields=["caller_instructions","updated_at"])
    messages=Module.objects.get(slug="messages")
    if MESSAGE_GUIDANCE.strip() not in messages.caller_instructions:
        messages.caller_instructions=messages.caller_instructions.rstrip()+MESSAGE_GUIDANCE
        messages.save(update_fields=["caller_instructions","updated_at"])
    create=Function.objects.filter(manifest_id="scheduled_tasks.create_task").first()
    if create:
        create.description="Create future work during normal conversation. Do not call this to deliver a due reminder; use messages.send_message when the due time arrives."
        schema=dict(create.params_schema); props=dict(schema.get("properties",{})); recurrence=dict(props.get("recurrence",{})); recurrence["description"]="once|daily|weekly|monthly; omit for once (null is also treated as once)"; props["recurrence"]=recurrence; schema["properties"]=props; create.params_schema=schema; create.save(update_fields=["description","params_schema","updated_at"])
    Task=apps.get_model("orchestration","ScheduledTask")
    for task in Task.objects.filter(status="completed",recurrence="once"):
        latest=task.runs.order_by("-started_at").first()
        if latest and latest.status == "failed":
            task.status="failed"; task.next_run_at=None; task.is_running=False
            task.save(update_fields=["status","next_run_at","is_running","updated_at"])
    for manifest_id in ("scheduled_tasks.list_tasks","scheduled_tasks.update_task"):
        function=Function.objects.filter(manifest_id=manifest_id).first()
        if function:
            schema=dict(function.params_schema); props=dict(schema.get("properties",{})); status=dict(props.get("status",{})); status["description"]="active|paused|completed|failed"; props["status"]=status; schema["properties"]=props; function.params_schema=schema; function.save(update_fields=["params_schema","updated_at"])

class Migration(migrations.Migration):
    dependencies=[("orchestration","0073_absolute_note_time_guidance")]
    operations=[
        migrations.AlterField(model_name="scheduledtask",name="status",field=models.CharField(choices=[("active","Active"),("paused","Paused"),("completed","Completed"),("failed","Failed"),("canceled","Canceled")],default="active",max_length=16)),
        migrations.RunPython(configure,migrations.RunPython.noop),
    ]
