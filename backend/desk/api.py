from datetime import datetime, time
from typing import Optional

from django.http import HttpRequest
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import BanRejection, BanWindow, OffsetSubmission, User
from desk.services import create_submission_with_ban_gate

api = NinjaAPI(title="数控刀补复核台", version="1.0")


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


class BanWindowIn(Schema):
    # 服务器本地钟点，HH:MM。start == end 视为全天禁交；start > end 视为跨夜。
    start_time: time
    end_time: time


class BanWindowOut(Schema):
    configured: bool
    start_time: Optional[time]
    end_time: Optional[time]
    is_banned_now: bool
    server_time: datetime


class BanRejectionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    rejected_by: Optional[str]
    start_time: time
    end_time: time
    server_time: datetime
    created_at: datetime


def _window_payload(window: Optional[BanWindow]) -> dict:
    # 状态判定只信服务器此刻，不接受任何前端钟点。
    now = timezone.now()
    if window is None:
        return {
            "configured": False,
            "start_time": None,
            "end_time": None,
            "is_banned_now": False,
            "server_time": now,
        }
    return {
        "configured": True,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "is_banned_now": window.contains(now),
        "server_time": now,
    }


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
    # 挡回判定与流水已在 service 的同一事务内提交，403 在事务提交后返回。
    result = create_submission_with_ban_gate(
        user=user,
        tool_code=tool_code,
        offset_um=body.offset_um,
    )
    if result.blocked:
        raise HttpError(403, result.message)
    return _to_out(result.submission)


@api.get("/ban/window", response=BanWindowOut, auth=bearer_auth)
def get_ban_window(request: HttpRequest):
    return _window_payload(BanWindow.get())


@api.put("/ban/window", response=BanWindowOut, auth=bearer_auth)
def update_ban_window(request: HttpRequest, body: BanWindowIn):
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "只读账号不能修改禁交钟点")
    window = BanWindow.get() or BanWindow(pk=BanWindow.SINGLETON_ID)
    window.start_time = body.start_time
    window.end_time = body.end_time
    window.updated_by = user
    window.save()
    return _window_payload(window)


@api.get("/ban/rejections", response=list[BanRejectionOut], auth=bearer_auth)
def list_ban_rejections(request: HttpRequest):
    rows = BanRejection.objects.select_related("rejected_by")[:200]
    return [
        BanRejectionOut(
            id=r.id,
            tool_code=r.tool_code,
            offset_um=r.offset_um,
            rejected_by=r.rejected_by.username if r.rejected_by else None,
            start_time=r.start_time,
            end_time=r.end_time,
            server_time=r.server_time,
            created_at=r.created_at,
        )
        for r in rows
    ]
