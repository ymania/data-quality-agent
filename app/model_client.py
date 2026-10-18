"""Model construction and explicit proxy selection for the local application."""

import hashlib
import os
from urllib.parse import urlsplit
from urllib.request import proxy_bypass

import httpx
from langchain_openai import ChatOpenAI


class ModelUnavailable(RuntimeError):
    pass


_last_probe = None


def _settings():
    return {
        "name": os.getenv("MODEL_NAME", "").strip(),
        "key": os.getenv("MODEL_API_KEY", "").strip(),
        "base_url": os.getenv("MODEL_BASE_URL", "").strip(),
        "mode": os.getenv("MODEL_PROXY_MODE", "auto").strip().lower(),
        "proxy": os.getenv("MODEL_PROXY_URL", "").strip(),
    }


def _fingerprint(settings):
    source = repr((tuple(sorted(settings.items())), os.getenv("HTTPS_PROXY"),
                   os.getenv("https_proxy"), os.getenv("HTTP_PROXY"),
                   os.getenv("http_proxy"), os.getenv("ALL_PROXY"),
                   os.getenv("all_proxy")))
    return hashlib.sha256(source.encode()).hexdigest()


def _proxy(settings):
    mode = settings["mode"]
    if mode == "direct":
        return None
    if mode == "custom":
        candidates = [settings["proxy"]]
    elif mode == "auto":
        target = urlsplit(settings["base_url"])
        if target.hostname and proxy_bypass(target.hostname):
            return None
        scheme = target.scheme
        names = ("HTTPS_PROXY", "https_proxy") if scheme == "https" else ("HTTP_PROXY", "http_proxy")
        candidates = [os.getenv(name, "") for name in names]
        candidates += [os.getenv("ALL_PROXY", ""), os.getenv("all_proxy", "")]
    else:
        raise ModelUnavailable("模型代理模式无效，请在 /setup 页面重新选择")
    for value in candidates:
        if not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname:
            if mode == "auto":
                raise ModelUnavailable("系统代理协议无效；请在 /setup 选择直连或填写有效的 HTTP/SOCKS5 代理")
            raise ModelUnavailable("代理地址需以 http://、https://、socks5:// 或 socks5h:// 开头")
        return value
    if mode == "custom":
        raise ModelUnavailable("请在 /setup 填写自定义代理地址")
    return None


def build_model():
    settings = _settings()
    if (not settings["name"] or not settings["key"] or not settings["base_url"]
            or settings["key"] == "replace-me" or settings["name"] == "your-tool-calling-model"):
        raise ModelUnavailable("模型尚未配置：请打开本机 /setup 页面填写模型接口和 API Key")
    base = urlsplit(settings["base_url"])
    if base.scheme not in {"http", "https"} or not base.hostname:
        raise ModelUnavailable("模型接口地址无效，请在 /setup 检查 base_url")
    proxy = _proxy(settings)
    options = {}
    if base.hostname == "api.deepseek.com" and settings["name"] in {"deepseek-flash", "deepseek-v4-pro"}:
        options["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        # Both OpenAI clients ignore inherited proxy variables. In auto mode we
        # select the scheme-specific proxy before a malformed ALL_PROXY fallback.
        sync_client = httpx.Client(proxy=proxy, trust_env=False)
        async_client = httpx.AsyncClient(proxy=proxy, trust_env=False)
        return ChatOpenAI(model=settings["name"], api_key=settings["key"],
                          base_url=settings["base_url"], http_client=sync_client,
                          http_async_client=async_client, **options)
    except Exception as exc:
        raise ModelUnavailable("模型客户端无法初始化，请检查 /setup 中的接口和代理配置") from exc


def probe_status():
    settings = _settings()
    configured = (all(settings[key] for key in ("name", "key", "base_url"))
                  and settings["name"] != "your-tool-calling-model"
                  and settings["key"] != "replace-me")
    if not configured:
        return {"model_configured": False, "model_state": "unconfigured"}
    if _last_probe and _last_probe[0] == _fingerprint(settings):
        return {"model_configured": True, "model_state": _last_probe[1]}
    return {"model_configured": True, "model_state": "untested"}


def test_model():
    """Check a real, read-only tool call; never touch business data."""
    global _last_probe
    settings = _settings()
    fingerprint = _fingerprint(settings)
    try:
        model = build_model()
        model_with_tool = model.bind_tools([{
            "type": "function",
            "function": {
                "name": "check_connection",
                "description": "Return a connectivity check without changing data.",
                "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                               "required": ["ok"]},
            },
        }])
        response = model_with_tool.invoke("请调用 check_connection 工具，参数 ok=true。不要执行其他操作。")
        if not any(call.get("name") == "check_connection" for call in response.tool_calls):
            raise ModelUnavailable("模型已应答，但未返回工具调用；请使用支持工具调用的模型")
    except ModelUnavailable:
        _last_probe = (fingerprint, "error")
        raise
    except Exception as exc:
        _last_probe = (fingerprint, "error")
        raise ModelUnavailable("模型连接或工具调用失败；请检查模型名称、密钥、网络与代理") from exc
    _last_probe = (fingerprint, "ok")
    return {"connected": True, "tool_calling": True}
