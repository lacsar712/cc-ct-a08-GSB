from datetime import datetime, time
from typing import Optional

from django.http import HttpRequest
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import CurfewSettings, OffsetSubmission, RejectionLog, User
from desk.services import evaluate_curfew, submit_offset_or_reject

api = NinjaAPI(title="数控刀补复核台", version="1.0")

HHMM = "%H:%M"


class HealthOut(Schema):
    status: str


class LoginIn(Schema):
    username: str
    password: str


class LoginOut(Schema):
    token: str
    username: str
    role: str
    can_write: bool


class SubmissionIn(Schema):
    tool_code: str
    offset_um: int


class SubmissionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    status: str
    verdict: str
    created_at: datetime
    reviewed_at: Optional[datetime]


class CurfewSettingsIn(Schema):
    # 仅接收钟点字符串，绝不接收任何客户端“当前时刻”
    start_time: str
    end_time: str
    enabled: bool = True


class CurfewSettingsOut(Schema):
    start_time: str
    end_time: str
    enabled: bool
    can_write: bool
    updated_by: Optional[str]
    updated_at: Optional[datetime]


class CurfewStatusOut(Schema):
    blocked: bool
    enabled: bool
    start_time: str
    end_time: str
    server_time: datetime
    server_clock: str
    reason: str


class RejectionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    window_start: str
    window_end: str
    server_time: datetime
    attempted_by: Optional[str]
    reason: str


def _to_out(row: OffsetSubmission) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        status=row.status,
        verdict=row.verdict or "",
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _parse_hhmm(value: str, field: str) -> time:
    if not isinstance(value, str):
        raise HttpError(400, f"{field} 格式应为 HH:MM")
    value = value.strip()
    for fmt in (HHMM, "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise HttpError(400, f"{field} 格式应为 HH:MM，例如 22:00")


def _settings_out(curfew: CurfewSettings, user: User) -> CurfewSettingsOut:
    return CurfewSettingsOut(
        start_time=curfew.start_time.strftime(HHMM),
        end_time=curfew.end_time.strftime(HHMM),
        enabled=curfew.enabled,
        can_write=user.can_write,
        updated_by=curfew.updated_by.username if curfew.updated_by_id else None,
        updated_at=curfew.updated_at,
    )


def _rejection_out(row: RejectionLog) -> RejectionOut:
    return RejectionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        window_start=row.window_start.strftime(HHMM),
        window_end=row.window_end.strftime(HHMM),
        server_time=row.server_time,
        attempted_by=row.attempted_by.username if row.attempted_by_id else None,
        reason=row.reason,
    )


@api.get("/health", response=HealthOut)
def health(request: HttpRequest):
    return {"status": "ok"}


@api.post("/auth/login", response=LoginOut)
def login(request: HttpRequest, body: LoginIn):
    try:
        user = User.objects.get(username=body.username)
    except User.DoesNotExist:
        raise HttpError(401, "用户名或密码错误")
    if not verify_password(body.password, user.password):
        raise HttpError(401, "用户名或密码错误")
    token = create_access_token(user)
    return {
        "token": token,
        "username": user.username,
        "role": user.role,
        "can_write": user.can_write,
    }


@api.get("/submissions", response=list[SubmissionOut], auth=bearer_auth)
def list_submissions(request: HttpRequest):
    rows = OffsetSubmission.objects.all()[:200]
    return [_to_out(r) for r in rows]


@api.get("/submissions/{submission_id}", response=SubmissionOut, auth=bearer_auth)
def get_submission(request: HttpRequest, submission_id: int):
    try:
        row = OffsetSubmission.objects.get(pk=submission_id)
    except OffsetSubmission.DoesNotExist:
        raise HttpError(404, "刀补记录不存在")
    return _to_out(row)


@api.post("/submissions", response=SubmissionOut, auth=bearer_auth)
def create_submission(request: HttpRequest, body: SubmissionIn):
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "当前账号只读，不能提交刀补")
    tool_code = body.tool_code.strip()
    if not tool_code:
        raise HttpError(400, "刀具编号不能为空")

    # 禁交判定与拒交流水在同一事务内落库：
    # 事务成功提交后才据此抛 403；若流水写库失败，整个事务回滚并返回 5xx，
    # 绝不会出现“挡回了但没流水”或“有流水却放行”的半截状态。
    submission, decision = submit_offset_or_reject(
        user=user,
        tool_code=tool_code,
        offset_um=body.offset_um,
    )
    if submission is None:
        raise HttpError(403, decision.reason)
    return _to_out(submission)


@api.get("/curfew/settings", response=CurfewSettingsOut, auth=bearer_auth)
def get_curfew_settings(request: HttpRequest):
    user: User = request.auth
    return _settings_out(CurfewSettings.get_solo(), user)


@api.put("/curfew/settings", response=CurfewSettingsOut, auth=bearer_auth)
def update_curfew_settings(request: HttpRequest, body: CurfewSettingsIn):
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "当前账号只读，不能修改禁交钟点")
    start_t = _parse_hhmm(body.start_time, "禁交开始钟点")
    end_t = _parse_hhmm(body.end_time, "禁交结束钟点")

    from django.db import transaction

    with transaction.atomic():
        curfew = CurfewSettings.get_solo()
        curfew.start_time = start_t
        curfew.end_time = end_t
        curfew.enabled = body.enabled
        curfew.updated_by = user
        curfew.save()
    # 无任何缓存：下一次提交立即读到新钟点，马上生效
    return _settings_out(curfew, user)


@api.get("/curfew/status", response=CurfewStatusOut, auth=bearer_auth)
def curfew_status(request: HttpRequest):
    decision = evaluate_curfew(CurfewSettings.get_solo())
    return CurfewStatusOut(
        blocked=decision.blocked,
        enabled=decision.enabled,
        start_time=decision.start_time.strftime(HHMM),
        end_time=decision.end_time.strftime(HHMM),
        server_time=decision.server_time,
        server_clock=decision.server_time.strftime("%Y-%m-%d %H:%M"),
        reason=decision.reason,
    )


@api.get("/curfew/rejections", response=list[RejectionOut], auth=bearer_auth)
def list_rejections(request: HttpRequest):
    rows = RejectionLog.objects.select_related("attempted_by").all()[:200]
    return [_rejection_out(r) for r in rows]
