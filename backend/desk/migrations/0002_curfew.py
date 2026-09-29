import desk.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("desk", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CurfewSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_time", models.TimeField(default=desk.models._default_curfew_start, verbose_name="禁交开始钟点")),
                ("end_time", models.TimeField(default=desk.models._default_curfew_end, verbose_name="禁交结束钟点")),
                ("enabled", models.BooleanField(default=True, verbose_name="是否启用禁交")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="curfew_updates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "禁交钟点设置",
                "verbose_name_plural": "禁交钟点设置",
            },
        ),
        migrations.CreateModel(
            name="RejectionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tool_code", models.CharField(max_length=32, verbose_name="刀具编号")),
                ("offset_um", models.IntegerField(verbose_name="刀补微米")),
                ("window_start", models.TimeField(verbose_name="判定时禁交开始")),
                ("window_end", models.TimeField(verbose_name="判定时禁交结束")),
                ("server_time", models.DateTimeField(db_index=True, verbose_name="服务器判定时刻")),
                ("reason", models.CharField(default="", max_length=200, verbose_name="挡回原因")),
                (
                    "attempted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rejection_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "禁交流水",
                "verbose_name_plural": "禁交流水",
                "ordering": ["-server_time", "-id"],
            },
        ),
    ]
