"""FastAPI endpoints and the single-page frontend."""

import os
from pathlib import Path

import pymysql
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app import quality, settings
from app.model_client import ModelUnavailable, probe_status, test_model

app = FastAPI(title="数据质量 Agent", version="1.0.0")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


from app.upload_api import router as upload_router, UploadLimits
app.add_middleware(UploadLimits)
app.include_router(upload_router)


class CreateRuleRequest(BaseModel):
    dataset_id: int | None = Field(default=None, ge=1)
    name: str
    table_name: str
    column_name: str
    rule_type: str
    params: dict = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=64)


class ChatRequest(BaseModel):
    dataset_id: int | None = Field(default=None, ge=1)
    table_name: str | None = None
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)


class RunRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mysql_host: str | None = None
    mysql_port: int | None = Field(default=None, ge=1, le=65535)
    mysql_user: str | None = None
    mysql_password: str | None = None
    model_name: str | None = None
    model_base_url: str | None = None
    model_api_key: str | None = None
    model_proxy_mode: str | None = None
    model_proxy_url: str | None = None


class InitializeRequest(BaseModel):
    admin_user: str | None = None
    admin_password: str | None = None


def _local_setup(request: Request):
    local_client = request.client and request.client.host in {"127.0.0.1", "::1"}
    local_container = os.getenv("APP_TRUST_DOCKER_LOCAL") == "1"
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1"} or not (local_client or local_container):
        raise HTTPException(403, "配置页面仅允许本机访问")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        raise HTTPException(403, "跨站请求不能修改配置")


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


def _error(exc):
    if isinstance(exc, ModelUnavailable):
        return HTTPException(503, str(exc))
    if isinstance(exc, quality.MissingResource):
        return HTTPException(404, str(exc))
    if isinstance(exc, pymysql.MySQLError):
        return HTTPException(503, "MySQL 连接或查询失败，请检查数据库服务及配置")
    if isinstance(exc, ValueError):
        return HTTPException(400, str(exc))
    return HTTPException(500, str(exc))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/setup")
def setup(request: Request):
    _local_setup(request)
    return FileResponse(STATIC / "setup.html", headers={"Cache-Control": "no-store"})


@app.get("/api/settings")
def get_settings(request: Request, response: Response):
    _local_setup(request)
    _no_store(response)
    return settings.public_settings()


@app.post("/api/settings")
def save_settings(request: Request, response: Response, body: SettingsRequest):
    _local_setup(request)
    _no_store(response)
    values = {key.upper(): str(value) for key, value in body.model_dump(exclude_unset=True).items() if value is not None}
    try:
        return settings.save_settings(values)
    except Exception as exc:
        raise _error(exc) from exc


@app.post("/api/settings/test-database")
def test_database(request: Request, response: Response):
    _local_setup(request)
    _no_store(response)
    try:
        return settings.test_database()
    except Exception as exc:
        raise _error(exc) from exc


@app.post("/api/settings/test-model")
def test_model_settings(request: Request, response: Response):
    _local_setup(request)
    _no_store(response)
    try:
        return test_model()
    except Exception as exc:
        raise _error(exc) from exc


@app.post("/api/settings/initialize-database")
def initialize_database(request: Request, response: Response, body: InitializeRequest):
    _local_setup(request)
    _no_store(response)
    try:
        return settings.initialize_demo(body.admin_user or None, body.admin_password or None)
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/health")
def health():
    try:
        columns = quality.describe_schema()
        database = "ok" if any(row["table_name"] == "demo_orders" for row in columns) else "unavailable"
    except Exception:
        database = "unavailable"
    return {"database": database, **probe_status()}


@app.get("/api/schema")
def schema():
    try:
        return quality.describe_schema()
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/rules")
def rules(limit: int = Query(default=20, ge=1, le=100), before_id: int | None = Query(default=None, ge=1)):
    try:
        return quality.list_rules(limit, before_id)
    except Exception as exc:
        raise _error(exc) from exc


@app.post("/api/rules")
def create_rule(body: CreateRuleRequest):
    try:
        return quality.manual_action(
            body.session_id, "页面创建质量规则", "create_quality_rule",
            lambda: quality.create_rule(body.name, body.table_name, body.column_name,
                                        body.rule_type, body.params, body.session_id, body.dataset_id),
        )
    except Exception as exc:
        raise _error(exc) from exc


@app.post("/api/rules/{rule_id}/run")
def run_rule(rule_id: int, body: RunRequest):
    try:
        return quality.manual_action(
            body.session_id, f"页面运行规则 #{rule_id}", "run_quality_rule",
            lambda: quality.run_rule(rule_id, body.session_id),
        )
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/results")
def results(limit: int = Query(default=20, ge=1, le=100), before_id: int | None = Query(default=None, ge=1)):
    try:
        return quality.list_results(limit, before_id)
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/results/{execution_id}")
def result(execution_id: int):
    try:
        return quality.get_result(execution_id=execution_id)
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/rules/{rule_id}")
def rule_detail(rule_id: int):
    try:
        return quality.get_rule(rule_id)
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/rules/{rule_id}/latest")
def latest(rule_id: int):
    try:
        return quality.get_result(rule_id=rule_id, latest=True)
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/sessions/{session_id}/messages")
def messages(session_id: str):
    if len(session_id) > 64:
        raise HTTPException(400, "会话 ID 过长")
    try:
        return quality.chat_history(session_id)
    except Exception as exc:
        raise _error(exc) from exc


@app.post("/api/chat")
def chat(body: ChatRequest):
    from app.agent import chat as agent_chat

    if not body.message.strip():
        raise HTTPException(400, "请输入请求内容")
    try:
        return agent_chat(body.session_id, body.message.strip(), body.dataset_id, body.table_name)
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise _error(exc) from exc
