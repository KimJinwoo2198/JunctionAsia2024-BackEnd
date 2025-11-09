from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VoiceSession",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("openai_session_id", models.CharField(max_length=128)),
                ("model", models.CharField(max_length=64)),
                ("voice", models.CharField(max_length=64)),
                ("modalities", models.JSONField(blank=True, default=list)),
                ("instructions", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("webrtc_url", models.URLField(blank=True, max_length=512)),
                ("client_secret_hash", models.CharField(max_length=64)),
                ("client_secret_last4", models.CharField(max_length=4)),
                ("client_secret_expires_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "생성됨"),
                            ("active", "진행중"),
                            ("ended", "종료됨"),
                            ("expired", "만료됨"),
                            ("failed", "실패"),
                        ],
                        default="created",
                        max_length=16,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="VoiceInteraction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("user", "사용자"),
                            ("assistant", "어시스턴트"),
                            ("system", "시스템"),
                        ],
                        max_length=16,
                    ),
                ),
                ("content", models.TextField(blank=True)),
                ("audio_url", models.URLField(blank=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="interactions",
                        to="voice_assistant.voicesession",
                    ),
                ),
            ],
            options={
                "ordering": ("created_at",),
            },
        ),
        migrations.AddField(
            model_name="voicesession",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="voice_sessions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="voicesession",
            index=models.Index(fields=["user", "created_at"], name="voice_assi_user_id_bb7603_idx"),
        ),
        migrations.AddIndex(
            model_name="voicesession",
            index=models.Index(fields=["status"], name="voice_assi_status_77b84f_idx"),
        ),
        migrations.AddIndex(
            model_name="voicesession",
            index=models.Index(fields=["openai_session_id"], name="voice_assi_openai__f0101c_idx"),
        ),
        migrations.AddIndex(
            model_name="voiceinteraction",
            index=models.Index(fields=["session", "created_at"], name="voice_assi_session__7ecdf2_idx"),
        ),
        migrations.AddIndex(
            model_name="voiceinteraction",
            index=models.Index(fields=["role"], name="voice_assi_role_661d3d_idx"),
        ),
    ]


