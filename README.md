# 数控刀补复核台

操作员提交刀具编号与刀补微米值；后台 worker 用 PostgreSQL 行锁（`select_for_update(skip_locked=True)`）认领待复核记录，按绝对值是否不超过 12 微米给出「合格」或「超差」。

**夜班禁交**：操作员可设定每天禁交起止钟点。提交刀补时，后台一律以**服务器时刻**（Asia/Shanghai）判定，落在起止钟点构成的**闭区间**内（含起止两端）即挡回并说明「正在禁交」；前端本机钟点不参与判定，无法蒙混。改钟点后下一次提交立即生效。每次挡回都在**同一事务**内追加一条禁交流水，流水落库失败则整体回滚，不会出现「有挡回无流水」或「有流水未挡回」。支持跨午夜窗（如 22:00–06:00）。

## 禁交台

菜单进入「禁交台」，一页含三块：

1. **禁交钟点设置**：起止钟点 + 启用开关；操作员可改，复核员（只读）只能看。
2. **此刻是否禁交**：调后端 `/curfew/status`，展示服务器时刻、是否禁交及挡回原因。
3. **禁交流水**：每次窗内挡回的尝试留痕（服务器判定时刻、刀具、刀补、判定时窗口快照、提交人、原因）。

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
| auditor | audit123456 | 只读：可看列表、钟点、此刻状态、流水，不能提交、不能改钟点 |

## 启动

```bash
cd projects/17-cnc-tool-offset-desk
docker compose up --build
```

健康检查：`GET http://localhost:8196/api/health` → `{"status":"ok"}`

## 禁交接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/curfew/settings` | 登录 | 禁交起止钟点、启用状态、最近修改人 |
| PUT | `/api/curfew/settings` | machinist | 改钟点，立即生效；只读员 403 |
| GET | `/api/curfew/status` | 登录 | 按服务器时刻返回此刻是否禁交、服务器钟点、原因 |
| GET | `/api/curfew/rejections` | 登录 | 禁交流水列表 |
| POST | `/api/submissions` | machinist | 窗内挡回 403 且同事务写流水；窗外正常提交 |

> 设置接口只接收钟点（`HH:MM`），不接收任何客户端「当前时间」；判定时刻只取自服务器 `timezone.now()`。

## 验收

1. machinist 登录后，种子数据应显示刀具 T01 合格（刀补 5 µm）、T09 超差（刀补 20 µm）。
2. 提交一条新刀补后，状态先为「待复核」，数秒内 worker 处理为「已完成」并给出结论。
3. auditor 登录后只能看列表，没有提交表单。
4. **禁交盖住现在再交应失败**：在禁交台把起止窗设到盖住当前服务器钟点，提交刀补返回 403 并提示正在禁交，禁交流水追加一条，复核列表不出现该刀补。
5. **挪开后再交应成功**：把禁交窗改到不覆盖此刻（或停用），同一刀补再交返回 200 并进待复核。
6. auditor 进入禁交台只能看钟点、此刻状态与流水，没有保存钟点的入口，直接调 PUT 返回 403。
7. 边界钟点（恰好等于起、止）按闭区间判为禁交。

## 测试

无 PostgreSQL 的本地环境可用 SQLite 跑后端测试：

```bash
cd backend
DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test desk
```

覆盖闭区间边界、跨午夜、窗内挡回 + 同事务流水、流水失败回滚、改钟点立即生效、只读员权限等。

## 目录

```text
backend/          Django 工程（config/、desk/、worker.py）
frontend/         SolidJS 单页
docker-compose.yml
PRD.md
```
