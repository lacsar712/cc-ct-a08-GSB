# 数控刀补复核台

操作员提交刀具编号与刀补微米值；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

夜班通过「禁交台」设定每日禁交起止钟点：后台一律按**服务器时刻**判定，落在闭区间（含起止钟点）内的提交被 403 挡回，并在同一数据库事务内追加一条禁交流水；改钟点立即生效，前端本地钟点不参与判定。

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Django 5 + django-ninja（ASGI / uvicorn） |
| 前端 | SolidJS + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |
| 鉴权 | JWT（python-jose），令牌存浏览器 localStorage |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3196 |
| 接口 | http://localhost:8196 |
| PostgreSQL | localhost:54396（库名 `cncoffset`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| machinist | machine123456 | 可提交刀补、可改禁交钟点 |
| auditor | audit123456 | 只读：可看列表、禁交钟点与禁交流水，不能改钟点、不能提交 |

## 启动

```bash
cd projects/17-cnc-tool-offset-desk
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 验收

1. machinist 登录后，种子数据应显示刀具 T01 合格（刀补 5 µm）、T09 超差（刀补 20 µm）。
2. 提交一条新刀补后，状态先为「待复核」，数秒内 worker 处理为「已完成」并给出结论。
3. auditor 登录后只能看列表，没有提交表单。
4. 菜单进入「禁交台」，可见钟点设置、此刻是否禁交（附服务器时刻）、禁交流水三块；auditor 只能看不能改。
5. 把禁交钟点设成盖住当前服务器时刻（含恰好等于起/止钟点），再交刀补应被挡回（HTTP 403，文案说明正在禁交），禁交流水同时增加一条；把窗口挪开后再交应成功且不留流水。
6. 起钟点晚于止钟点按跨夜处理；起止相同按全天禁交处理。

## 禁交相关接口

| 方法/路径 | 权限 | 说明 |
|-----------|------|------|
| `GET /api/ban/window` | 登录用户 | 返回钟点、`is_banned_now` 与 `server_time`（后台裁决） |
| `PUT /api/ban/window` | 操作员 | 修改每日起止钟点，立即生效 |
| `GET /api/ban/rejections` | 登录用户 | 禁交流水（只读员可看） |
| `POST /api/submissions` | 操作员 | 窗内 403 挡回；挡回判定与流水同事务 |

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```
