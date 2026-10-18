"""Local setup: persist credentials and prepare the bundled MySQL demo."""

import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pymysql
from dotenv import dotenv_values, load_dotenv


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.getenv("DQ_ENV_FILE", str(ROOT / ".env")))
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)
DEFAULTS = {
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "dq_app",
    "MYSQL_PASSWORD": "",
    "MYSQL_DATABASE": "data_quality_agent",
    "MODEL_NAME": "",
    "MODEL_BASE_URL": "",
    "MODEL_API_KEY": "",
    "MODEL_PROXY_MODE": "auto",
    "MODEL_PROXY_URL": "",
    "APP_HOST": "127.0.0.1",
    "APP_PORT": "8000",
}
EDITABLE = {"MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD",
            "MODEL_NAME", "MODEL_BASE_URL", "MODEL_API_KEY",
            "MODEL_PROXY_MODE", "MODEL_PROXY_URL"}
SECRET = {"MYSQL_PASSWORD", "MODEL_API_KEY"}
_lock = threading.Lock()


def _current():
    return {key: os.getenv(key, default) for key, default in DEFAULTS.items()}


def public_settings():
    data = _current()
    return {
        "mysql_host": data["MYSQL_HOST"],
        "mysql_port": data["MYSQL_PORT"],
        "mysql_user": data["MYSQL_USER"],
        "mysql_database": data["MYSQL_DATABASE"],
        "mysql_password_set": bool(data["MYSQL_PASSWORD"]),
        "model_name": data["MODEL_NAME"],
        "model_base_url": data["MODEL_BASE_URL"],
        "model_api_key_set": bool(data["MODEL_API_KEY"] and data["MODEL_API_KEY"] != "replace-me"),
        "model_proxy_mode": data["MODEL_PROXY_MODE"],
        "model_proxy_url": data["MODEL_PROXY_URL"],
    }


def _validate(updates):
    unknown = set(updates) - EDITABLE
    if unknown:
        raise ValueError("包含不支持的配置项")
    for key, value in updates.items():
        if not isinstance(value, str) or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError(f"{key} 格式不正确")
        if len(value) > 2048:
            raise ValueError(f"{key} 过长")
        if key not in SECRET | {"MODEL_PROXY_URL"} and not value.strip():
            raise ValueError(f"{key} 不能为空")
    if "MODEL_PROXY_MODE" in updates and updates["MODEL_PROXY_MODE"] not in {"auto", "direct", "custom"}:
        raise ValueError("模型代理模式无效")
    if updates.get("MODEL_PROXY_URL"):
        parsed = urlsplit(updates["MODEL_PROXY_URL"])
        if (parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("代理地址需为不含账号密码的 HTTP 或 SOCKS5 URL")
    if "MYSQL_PORT" in updates:
        try:
            port = int(updates["MYSQL_PORT"])
        except ValueError as exc:
            raise ValueError("MySQL 端口必须是数字") from exc
        if not 1 <= port <= 65535:
            raise ValueError("MySQL 端口需在 1 到 65535 之间")
        updates["MYSQL_PORT"] = str(port)
    if "MODEL_BASE_URL" in updates:
        parsed = urlsplit(updates["MODEL_BASE_URL"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/").endswith("/chat/completions"):
            raise ValueError("模型接口需填写 http(s) base_url，不能包含密钥或 /chat/completions")
    if updates.get("MODEL_API_KEY") == "replace-me" or updates.get("MYSQL_PASSWORD") == "change-me":
        raise ValueError("请填写真实密钥，不要使用示例值")


def save_settings(updates):
    """Atomically save a selected set of fields; blank secret fields keep old values."""
    updates = dict(updates)
    updates = {key: value for key, value in updates.items() if key not in SECRET or value}
    _validate(updates)
    with _lock:
        if ENV_FILE.is_symlink():
            raise ValueError(".env 是符号链接，拒绝写入密钥")
        stored = {key: value for key, value in dotenv_values(ENV_FILE).items() if value is not None} if ENV_FILE.exists() else {}
        # Include effective container overrides such as MYSQL_HOST=mysql when
        # first creating the persistent settings file.
        merged = {**DEFAULTS, **stored, **_current(), **updates}
        if merged["MODEL_PROXY_MODE"] == "custom" and not merged["MODEL_PROXY_URL"]:
            raise ValueError("自定义代理模式需要填写代理地址")
        fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=ENV_FILE.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                for key, value in merged.items():
                    out.write(f"{key}={json.dumps(str(value), ensure_ascii=False)}\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_name, ENV_FILE)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        for key, value in updates.items():
            os.environ[key] = value
    return public_settings()


def _connect(*, user=None, password=None, database=None):
    data = _current()
    return pymysql.connect(
        host=data["MYSQL_HOST"], port=int(data["MYSQL_PORT"]),
        user=user or data["MYSQL_USER"],
        password=data["MYSQL_PASSWORD"] if password is None else password,
        database=database, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        connect_timeout=5, read_timeout=30, write_timeout=30,
    )


def test_database():
    with _connect(database=_current()["MYSQL_DATABASE"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM demo_orders")
            total = cursor.fetchone()["total"]
    return {"connected": True, "demo_orders": total}


def _statements(path):
    # Bundled SQL has no stored procedures or semicolons inside string values.
    lines = (line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("--"))
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def initialize_demo(admin_user=None, admin_password=None):
    """Create schema and seed baseline only when the order table is empty."""
    if bool(admin_user) != bool(admin_password):
        raise ValueError("临时管理员用户名和密码请一起填写，或都留空")
    if _current()["MYSQL_DATABASE"] != "data_quality_agent":
        raise ValueError("演示初始化只支持 data_quality_agent 库")
    with _connect(user=admin_user, password=admin_password) as connection:
        with connection.cursor() as cursor:
            for statement in _statements(ROOT / "sql" / "schema.sql"):
                cursor.execute(statement)
            cursor.execute("SELECT COUNT(*) AS total FROM demo_orders")
            total = cursor.fetchone()["total"]
            seeded = total == 0
            if seeded:
                for statement in _statements(ROOT / "sql" / "seed.sql"):
                    cursor.execute(statement)
        # Use the administrator connection for upgrades. The ordinary app
        # account can remain limited to reading and writing business data.
        from app.datasets import ensure_schema
        ensure_schema(connection)
    return {"schema_ready": True, "seeded": seeded,
            "message": "已创建表并写入 20 条基准订单" if seeded else f"表已就绪，保留现有 {total} 条订单及历史执行"}
