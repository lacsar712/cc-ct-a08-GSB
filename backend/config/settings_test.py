from .settings import *  # noqa: F401,F403

# 本地无 PostgreSQL 时用内存 SQLite 跑迁移与测试（生产仍用 Postgres）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
