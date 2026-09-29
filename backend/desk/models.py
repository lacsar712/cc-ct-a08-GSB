from datetime import time

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MACHINIST = "machinist", "操作员"
        AUDITOR = "auditor", "复核员"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MACHINIST,
    )

    @property
    def can_write(self) -> bool:
        return self.role == self.Role.MACHINIST


class OffsetSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待复核"
        PROCESSING = "processing", "复核中"
        DONE = "done", "已完成"

    class Verdict(models.TextChoices):
        PASS = "合格", "合格"
        FAIL = "超差", "超差"

    tool_code = models.CharField(max_length=32, db_index=True)
    offset_um = models.IntegerField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    verdict = models.CharField(
        max_length=8,
        choices=Verdict.choices,
        blank=True,
        default="",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tool_code} {self.offset_um}µm"


def _default_curfew_start() -> time:
    # 默认夜间停机：22:00 起禁交
    return time(22, 0)


def _default_curfew_end() -> time:
    # 至次日 06:00 解交
    return time(6, 0)


class CurfewSettings(models.Model):
    """禁交钟点设置（全系统单行，pk 恒为 1）。"""

    start_time = models.TimeField("禁交开始钟点", default=_default_curfew_start)
    end_time = models.TimeField("禁交结束钟点", default=_default_curfew_end)
    enabled = models.BooleanField("是否启用禁交", default=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="curfew_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "禁交钟点设置"
        verbose_name_plural = verbose_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "CurfewSettings":
        obj = cls.objects.filter(pk=1).first()
        if obj is None:
            obj = cls(pk=1)
            obj.save()
        return obj

    def __str__(self) -> str:
        return f"禁交 {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class RejectionLog(models.Model):
    """禁交挡回流水：窗内每次提交尝试留痕。"""

    tool_code = models.CharField("刀具编号", max_length=32)
    offset_um = models.IntegerField("刀补微米")
    # 判定时快照的禁交窗起止，避免事后改窗导致流水含义漂移
    window_start = models.TimeField("判定时禁交开始")
    window_end = models.TimeField("判定时禁交结束")
    server_time = models.DateTimeField("服务器判定时刻", db_index=True)
    attempted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejection_logs",
    )
    reason = models.CharField("挡回原因", max_length=200, default="")

    class Meta:
        verbose_name = "禁交流水"
        verbose_name_plural = verbose_name
        ordering = ["-server_time", "-id"]

    def __str__(self) -> str:
        return f"禁交挡回 {self.tool_code} @ {self.server_time:%Y-%m-%d %H:%M}"
