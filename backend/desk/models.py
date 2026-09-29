from datetime import datetime

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


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


class BanWindow(models.Model):
    """每日禁交钟点（单例，pk 恒为 1）。起止均为服务器本地钟点。

    start < end 表示同一天区间；start > end 表示跨夜（夜班）；
    start == end 表示全天禁交。判定一律以服务器时刻为准。
    """

    SINGLETON_ID = 1

    start_time = models.TimeField(verbose_name="每日禁交起")
    end_time = models.TimeField(verbose_name="每日禁交止")
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ban_window_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "禁交钟点"
        verbose_name_plural = "禁交钟点"

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "BanWindow | None":
        return cls.objects.filter(pk=cls.SINGLETON_ID).first()

    def contains(self, moment: datetime) -> bool:
        """闭区间判定：起止钟点都算禁交。moment 须为带时区的服务器时刻。"""
        t = timezone.localtime(moment).time()
        if self.start_time == self.end_time:
            return True  # 起止相同即全天禁交
        if self.start_time < self.end_time:
            return self.start_time <= t <= self.end_time
        # 跨夜：[start, 24:00) ∪ [00:00, end]
        return t >= self.start_time or t <= self.end_time


class BanRejection(models.Model):
    """禁交挡回流水：每挡一次写一条，与挡回判定同一事务落库。"""

    tool_code = models.CharField(max_length=32)
    offset_um = models.IntegerField()
    rejected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ban_rejections",
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    server_time = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"禁交挡回 {self.tool_code} @ {self.server_time:%Y-%m-%d %H:%M:%S}"
