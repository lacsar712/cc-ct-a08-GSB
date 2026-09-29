import json
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from desk.auth_utils import create_access_token
from desk.models import CurfewSettings, OffsetSubmission, RejectionLog, User
from desk.services import is_within_curfew
import desk.services as services

SH = ZoneInfo("Asia/Shanghai")


def sh(hour, minute, day=29):
    return datetime(2026, 9, day, hour, minute, tzinfo=SH)


def freeze(at):
    """固定 services 看到的服务器时刻（绝不来自客户端）。"""
    return patch.object(services.timezone, "now", return_value=at)


class WindowBoundaryTests(TestCase):
    def test_same_day_closed_interval_includes_both_ends(self):
        s, e = time(9, 0), time(17, 0)
        self.assertFalse(is_within_curfew(time(8, 59), s, e))
        self.assertTrue(is_within_curfew(time(9, 0), s, e))
        self.assertTrue(is_within_curfew(time(12, 0), s, e))
        self.assertTrue(is_within_curfew(time(17, 0), s, e))
        self.assertFalse(is_within_curfew(time(17, 1), s, e))

    def test_overnight_closed_interval(self):
        s, e = time(22, 0), time(6, 0)
        self.assertTrue(is_within_curfew(time(22, 0), s, e))
        self.assertTrue(is_within_curfew(time(23, 30), s, e))
        self.assertTrue(is_within_curfew(time(0, 0), s, e))
        self.assertTrue(is_within_curfew(time(6, 0), s, e))
        self.assertFalse(is_within_curfew(time(6, 1), s, e))
        self.assertFalse(is_within_curfew(time(21, 59), s, e))
        self.assertFalse(is_within_curfew(time(12, 0), s, e))

    def test_equal_start_end_means_all_day(self):
        s = e = time(12, 30)
        self.assertTrue(is_within_curfew(time(0, 0), s, e))
        self.assertTrue(is_within_curfew(time(12, 30), s, e))
        self.assertTrue(is_within_curfew(time(23, 59), s, e))


class CurfewApiTests(TestCase):
    def setUp(self):
        from django.test import Client

        self.client = Client()
        self.machinist = User.objects.create_user(
            username="m", password="x", role=User.Role.MACHINIST
        )
        self.auditor = User.objects.create_user(
            username="a", password="x", role=User.Role.AUDITOR
        )
        self.mtoken = create_access_token(self.machinist)
        self.atoken = create_access_token(self.auditor)
        self.curfew = CurfewSettings.get_solo()
        self.curfew.start_time = time(22, 0)
        self.curfew.end_time = time(6, 0)
        self.curfew.enabled = True
        self.curfew.save()

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def post_submission(self, token, tool="T01", offset=5):
        return self.client.post(
            "/api/submissions",
            data=json.dumps({"tool_code": tool, "offset_um": offset}),
            content_type="application/json",
            **self.auth(token),
        )

    # ---- 窗内挡回 + 流水 ----
    def test_blocked_inside_window_writes_log_and_no_submission(self):
        with freeze(sh(23, 0)):
            resp = self.post_submission(self.mtoken)
        self.assertEqual(resp.status_code, 403)
        msg = resp.json()["detail"]
        self.assertIn("禁交", msg)
        self.assertIn("23:00", msg)  # 说明正在禁交 + 服务器时刻
        self.assertEqual(OffsetSubmission.objects.count(), 0)
        logs = RejectionLog.objects.all()
        self.assertEqual(logs.count(), 1)
        log = logs[0]
        self.assertEqual(log.tool_code, "T01")
        self.assertEqual(log.offset_um, 5)
        self.assertEqual(log.window_start, time(22, 0))  # 判定时窗口快照
        self.assertEqual(log.window_end, time(6, 0))
        self.assertEqual(log.attempted_by_id, self.machinist.id)

    def test_blocked_at_exact_boundaries(self):
        for at in (sh(22, 0), sh(6, 0, day=30)):
            with freeze(at):
                resp = self.post_submission(self.mtoken)
            self.assertEqual(resp.status_code, 403, f"边界 {at:%H:%M} 应挡回")
        self.assertEqual(RejectionLog.objects.count(), 2)

    # ---- 窗外放行 ----
    def test_allowed_outside_window(self):
        with freeze(sh(14, 0)):
            resp = self.post_submission(self.mtoken)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OffsetSubmission.objects.count(), 1)
        self.assertEqual(RejectionLog.objects.count(), 0)
        self.assertEqual(OffsetSubmission.objects.get().status, "pending")

    def test_disabled_curfew_allows_even_inside_window(self):
        self.curfew.enabled = False
        self.curfew.save()
        with freeze(sh(23, 0)):
            resp = self.post_submission(self.mtoken)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RejectionLog.objects.count(), 0)

    # ---- 改钟点立即生效：盖住→失败，挪开→成功 ----
    def test_changing_window_takes_effect_immediately(self):
        # 14:00 本不在 22–06 窗内，先把窗口盖到此刻
        r = self.client.put(
            "/api/curfew/settings",
            data=json.dumps({"start_time": "13:00", "end_time": "15:00", "enabled": True}),
            content_type="application/json",
            **self.auth(self.mtoken),
        )
        self.assertEqual(r.status_code, 200)
        with freeze(sh(14, 0)):
            self.assertEqual(self.post_submission(self.mtoken).status_code, 403)
        # 再把窗口挪开
        self.client.put(
            "/api/curfew/settings",
            data=json.dumps({"start_time": "01:00", "end_time": "02:00", "enabled": True}),
            content_type="application/json",
            **self.auth(self.mtoken),
        )
        with freeze(sh(14, 0)):
            self.assertEqual(self.post_submission(self.mtoken).status_code, 200)

    # ---- 只读员：可看不可改 ----
    def test_auditor_can_read_settings_status_logs_but_not_change(self):
        self.assertEqual(
            self.client.get("/api/curfew/settings", **self.auth(self.atoken)).status_code, 200
        )
        self.assertEqual(
            self.client.get("/api/curfew/status", **self.auth(self.atoken)).status_code, 200
        )
        self.assertEqual(
            self.client.get("/api/curfew/rejections", **self.auth(self.atoken)).status_code, 200
        )
        r = self.client.put(
            "/api/curfew/settings",
            data=json.dumps({"start_time": "01:00", "end_time": "02:00", "enabled": True}),
            content_type="application/json",
            **self.auth(self.atoken),
        )
        self.assertEqual(r.status_code, 403)
        # 钟点未被改动
        self.curfew.refresh_from_db()
        self.assertEqual(self.curfew.start_time, time(22, 0))
        # 只读员在窗外也不能提交
        with freeze(sh(14, 0)):
            self.assertEqual(self.post_submission(self.atoken).status_code, 403)

    # ---- status 接口以后端服务器时刻为准 ----
    def test_status_reflects_server_clock(self):
        with freeze(sh(23, 0)):
            data = self.client.get("/api/curfew/status", **self.auth(self.mtoken)).json()
        self.assertTrue(data["blocked"])
        self.assertIn("23:00", data["server_clock"])
        self.assertTrue(data["reason"])

    # ---- 同事务原子性：流水落库失败则整体回滚，不得留下半截 ----
    def test_rollback_when_rejection_insert_fails(self):
        def boom(*args, **kwargs):
            raise RuntimeError("rejection log insert failed")

        with freeze(sh(23, 0)), patch.object(
            RejectionLog.objects, "create", side_effect=boom
        ):
            with self.assertRaises(RuntimeError):
                self.post_submission(self.mtoken)
        self.assertEqual(OffsetSubmission.objects.count(), 0)
        self.assertEqual(RejectionLog.objects.count(), 0)

    def test_settings_invalid_time_rejected(self):
        r = self.client.put(
            "/api/curfew/settings",
            data=json.dumps({"start_time": "99:99", "end_time": "02:00", "enabled": True}),
            content_type="application/json",
            **self.auth(self.mtoken),
        )
        self.assertEqual(r.status_code, 400)
