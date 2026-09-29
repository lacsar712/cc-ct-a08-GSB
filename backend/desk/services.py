from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from desk.models import CurfewSettings, OffsetSubmission


def evaluate_verdict(offset_um: int) -> str:
    if abs(offset_um) <= settings.OFFSET_TOLERANCE_UM:
        return OffsetSubmission.Verdict.PASS
    return OffsetSubmission.Verdict.FAIL


def apply_verdict(submission: OffsetSubmission) -> None:
    submission.verdict = evaluate_verdict(submission.offset_um)
    submission.status = OffsetSubmission.Status.DONE
    submission.reviewed_at = timezone.now()
    submission.save(
        update_fields=["verdict", "status", "reviewed_at"],
    )


def _minute_of_day(t: time) -> int:
    return t.hour * 60 + t.minute


def is_within_curfew(now_t: time, start_t: time, end_t: time) -> bool:
    """服务器钟点是否落在禁交闭区间内（含起止两端，按分钟比较）。

    start > end 表示跨午夜窗（如 22:00–06:00）；
    start == end 视为全天禁交（要放行请关闭启用开关）。
    """
    now_m = _minute_of_day(now_t)
    start_m = _minute_of_day(start_t)
    end_m = _minute_of_day(end_t)
    if start_m == end_m:
        return True
    if start_m < end_m:
        return start_m <= now_m <= end_m
    return now_m >= start_m or now_m <= end_m


def server_local_time(now: Optional[datetime] = None) -> datetime:
    """取服务器时刻并按服务端时区（Asia/Shanghai）本地化。绝不采用客户端钟点。"""
    now = now or timezone.now()
    return timezone.localtime(now, timezone.get_current_timezone())


@dataclass
class CurfewDecision:
    blocked: bool
    server_time: datetime
    start_time: time
    end_time: time
    enabled: bool

    @property
    def reason(self) -> str:
        if not self.enabled:
            return ""
        return (
            f"当前服务器时刻 {self.server_time:%Y-%m-%d %H:%M} 落在禁交窗 "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M}（闭区间，含起止钟点）内，"
            "正在禁交，禁止提交刀补"
        )


def evaluate_curfew(
    curfew: CurfewSettings,
    now: Optional[datetime] = None,
) -> CurfewDecision:
    server_now = server_local_time(now)
    blocked = bool(curfew.enabled) and is_within_curfew(
        server_now.time(), curfew.start_time, curfew.end_time
    )
    return CurfewDecision(
        blocked=blocked,
        server_time=server_now,
        start_time=curfew.start_time,
        end_time=curfew.end_time,
        enabled=curfew.enabled,
    )


def submit_offset_or_reject(*, user, tool_code: str, offset_um: int):
    """提交刀补；若服务器时刻落在禁交窗则在同一事务内写拒交流水。

    返回到 (submission, decision)：
    - 放行：submission 为新建记录，decision.blocked 为 False；
    - 挡回：submission 为 None，decision.blocked 为 True，流水已与判定同事务提交。
    流水插入失败会抛出并整体回滚，绝不会出现有挡回无流水。
    """
    from desk.models import RejectionLog

    with transaction.atomic():
        # 锁定单行设置，使本次判定与改钟点互斥，杜绝判定瞬间被改窗钻空
        curfew = (
            CurfewSettings.objects.select_for_update().filter(pk=1).first()
        )
        if curfew is None:
            CurfewSettings.get_solo()
            curfew = CurfewSettings.objects.select_for_update().get(pk=1)
        decision = evaluate_curfew(curfew)

        if decision.blocked:
            # 与挡回判定同一事务：先落流水，随事务一起提交
            RejectionLog.objects.create(
                tool_code=tool_code,
                offset_um=offset_um,
                window_start=decision.start_time,
                window_end=decision.end_time,
                server_time=decision.server_time,
                attempted_by=user,
                reason=decision.reason,
            )
            return None, decision

        submission = OffsetSubmission.objects.create(
            tool_code=tool_code,
            offset_um=offset_um,
            submitted_by=user,
            status=OffsetSubmission.Status.PENDING,
        )
        return submission, decision
