from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from desk.models import BanRejection, BanWindow, OffsetSubmission, User


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


@dataclass
class SubmissionGateResult:
    blocked: bool
    submission: Optional[OffsetSubmission] = None
    rejection: Optional[BanRejection] = None
    message: str = ""


def create_submission_with_ban_gate(*, user: User, tool_code: str, offset_um: int) -> SubmissionGateResult:
    """以服务器时刻判定禁交窗口；挡回判定与流水写在同一事务里。

    - 落在闭区间内：锁单例行 → 取服务器时刻判定 → 写 BanRejection，随事务一起提交，
      返回 blocked=True。事务提交后调用方才回 403，保证「有挡回必有流水」。
    - 不在窗内：创建刀补提交，无任何流水。
    事务内任何一步失败整体回滚，不会留下有挡回无流水、或有流水未挡回的半截。
    """
    with transaction.atomic():
        window = BanWindow.objects.select_for_update().filter(pk=BanWindow.SINGLETON_ID).first()
        server_at = timezone.now()
        if window is not None and window.contains(server_at):
            rejection = BanRejection.objects.create(
                tool_code=tool_code,
                offset_um=offset_um,
                rejected_by=user,
                start_time=window.start_time,
                end_time=window.end_time,
                server_time=server_at,
            )
            local_at = timezone.localtime(server_at)
            message = (
                f"此刻服务器时间 {local_at:%H:%M:%S} 正处在每日禁交时段"
                f"（{window.start_time:%H:%M}–{window.end_time:%H:%M}，含起止钟点），刀补暂不接收"
            )
            return SubmissionGateResult(blocked=True, rejection=rejection, message=message)

        submission = OffsetSubmission.objects.create(
            tool_code=tool_code,
            offset_um=offset_um,
            submitted_by=user,
            status=OffsetSubmission.Status.PENDING,
        )
        return SubmissionGateResult(blocked=False, submission=submission)
