"""产品后端 FastAPI 入口。"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.agent_runtime import AgentRuntimeService
from backend.config import BackendConfig
from backend.sandbox.opensandbox_provider import OpenSandboxProvider
from backend.security import (
    build_session_cookie,
    expire_after,
    hash_password,
    hash_session_token,
    new_session_token,
    utcnow,
    verify_password,
)
from backend.store import BackendStore
from agent.runtime.public_api import AgentRuntimeFacade


class RegisterRequest(BaseModel):
    """注册请求。"""

    login_name: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    """登录请求。"""

    login_name: str
    password: str


class ThreadCreateRequest(BaseModel):
    """新建线程请求。"""

    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """聊天请求。"""

    message: str


class SandboxExecuteRequest(BaseModel):
    """OpenSandbox Python 执行请求。"""

    task: str = ""
    context: str = ""
    packages: List[str] = Field(default_factory=list)
    timeout_seconds: int = 180
    code: str
    trace_id: str = ""
    thread_id: str = ""
    run_id: str = ""
    message_id: str = ""


cfg = BackendConfig.load()
store = BackendStore(cfg.postgres_url)
sandbox_provider = OpenSandboxProvider(cfg)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """统一管理 startup/shutdown 生命周期。"""
    store.init_tables()
    cfg.artifact_root.mkdir(parents=True, exist_ok=True)
    app.state.agent_runtime = AgentRuntimeService(AgentRuntimeFacade(cfg.agent_config))
    try:
        yield
    finally:
        runtime = getattr(app.state, "agent_runtime", None)
        if runtime is not None:
            facade = getattr(runtime, "facade", None)
            if facade is not None and hasattr(facade, "close"):
                facade.close()


app = FastAPI(title="Fusion Product Backend", lifespan=app_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_agent_runtime_service() -> AgentRuntimeService:
    """读取 startup 阶段初始化的 AgentRuntimeService。"""
    runtime = getattr(app.state, "agent_runtime", None)
    if runtime is None:
        raise RuntimeError("AgentRuntimeService 尚未初始化。")
    return runtime


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """构造安全的用户输出。"""
    return {
        "id": str(user.get("id") or ""),
        "login_name": str(user.get("login_name") or ""),
        "display_name": str(user.get("display_name") or ""),
        "status": str(user.get("status") or ""),
        "created_at": user.get("created_at").isoformat()
        if user.get("created_at")
        else None,
        "last_login_at": user.get("last_login_at").isoformat()
        if user.get("last_login_at")
        else None,
    }


def get_current_user(
    request: Request,
) -> Dict[str, Any]:
    """基于 Cookie 会话解析当前用户。"""
    fusion_session = request.cookies.get(cfg.session_cookie_name)
    if not fusion_session:
        raise HTTPException(status_code=401, detail="未登录")
    token_hash = hash_session_token(fusion_session)
    user = store.get_user_by_session_token_hash(token_hash)
    if not user:
        raise HTTPException(status_code=401, detail="登录态无效")
    expires_at = user.get("expires_at")
    if expires_at and expires_at <= utcnow():
        store.delete_session(token_hash)
        raise HTTPException(status_code=401, detail="登录态已过期")
    return user


def require_service_token(x_service_token: Optional[str] = Header(default=None)) -> None:
    """校验内部沙箱调用令牌。"""
    if x_service_token != cfg.sandbox_service_token:
        raise HTTPException(status_code=401, detail="服务令牌无效")


@app.get("/health")
def health() -> Dict[str, Any]:
    """健康检查。"""
    return {"status": "ok", "service": "backend"}


@app.post("/api/auth/register")
def register(payload: RegisterRequest, response: Response, request: Request) -> Dict[str, Any]:
    """注册并自动登录。"""
    display_name = payload.display_name or payload.login_name
    user = store.create_user(
        login_name=payload.login_name.strip(),
        password_hash=hash_password(payload.password),
        display_name=display_name.strip(),
    )
    token = new_session_token()
    store.create_session(
        user_id=user["id"],
        session_token_hash=hash_session_token(token),
        expires_at=expire_after(cfg.session_ttl_hours),
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "",
    )
    cookie = build_session_cookie(token, max_age_hours=cfg.session_ttl_hours)
    response.set_cookie(cfg.session_cookie_name, cookie["key"], httponly=cookie["httponly"], samesite=cookie["samesite"], secure=cookie["secure"], max_age=cookie["max_age"], path=cookie["path"])
    return {"user": _public_user(user)}


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response, request: Request) -> Dict[str, Any]:
    """账号密码登录。"""
    user = store.get_user_by_login_name(payload.login_name.strip())
    if not user or not verify_password(payload.password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = new_session_token()
    store.create_session(
        user_id=user["id"],
        session_token_hash=hash_session_token(token),
        expires_at=expire_after(cfg.session_ttl_hours),
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "",
    )
    store.touch_last_login(user["id"], utcnow())
    cookie = build_session_cookie(token, max_age_hours=cfg.session_ttl_hours)
    response.set_cookie(cfg.session_cookie_name, cookie["key"], httponly=cookie["httponly"], samesite=cookie["samesite"], secure=cookie["secure"], max_age=cookie["max_age"], path=cookie["path"])
    return {"user": _public_user(store.get_user_by_id(user["id"]))}


@app.post("/api/auth/logout")
def logout(
    response: Response,
    request: Request,
) -> Dict[str, Any]:
    """退出登录。"""
    fusion_session = request.cookies.get(cfg.session_cookie_name)
    if fusion_session:
        store.delete_session(hash_session_token(fusion_session))
    response.delete_cookie(cfg.session_cookie_name, path="/")
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """返回当前用户。"""
    return {"user": _public_user(user)}


@app.get("/api/threads")
def list_threads(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """列出用户线程。"""
    return {"threads": store.list_threads(user["id"])}


@app.post("/api/threads")
def create_thread(payload: ThreadCreateRequest, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """创建线程。"""
    title = (payload.title or "新会话").strip()
    thread = store.create_thread(owner_user_id=user["id"], title=title, metadata=payload.metadata)
    return {"thread": thread}


@app.get("/api/threads/{thread_id}")
def get_thread(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """读取线程详情。"""
    return {"thread": store.get_thread(owner_user_id=user["id"], thread_id=thread_id)}


@app.get("/api/threads/{thread_id}/messages")
def list_thread_messages(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """读取线程消息。"""
    store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    messages = store.list_messages(thread_id)
    return {"messages": messages}


@app.get("/api/threads/{thread_id}/artifacts")
def list_thread_artifacts(thread_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """读取线程产物。"""
    store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    return {"artifacts": store.list_thread_artifacts(thread_id)}


@app.get("/api/threads/{thread_id}/runs/{run_id}/events")
def list_run_events(thread_id: str, run_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """读取运行过程事件。"""
    store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    return {"events": store.list_run_events(thread_id=thread_id, run_id=run_id)}


@app.post("/api/threads/{thread_id}/chat/stream")
def chat_stream(thread_id: str, payload: ChatRequest, user: Dict[str, Any] = Depends(get_current_user)) -> StreamingResponse:
    """产品级流式聊天接口。"""
    thread = store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    message_text = payload.message.strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    if not str(thread.get("title") or "").strip():
        store.update_thread(user["id"], thread_id, title=message_text[:32])
    user_message = store.save_message(
        thread_id=thread_id,
        role="user",
        content={"text": message_text},
        metadata={},
    )
    store.update_thread(user["id"], thread_id, status="running")
    run_id = str(uuid.uuid4())
    store.save_run_event(
        thread_id=thread_id,
        run_id=run_id,
        event_index=1,
        event_type="run_started",
        title="开始执行",
        summary=message_text[:120],
        status="running",
        payload={"user_message_id": user_message["id"]},
        message_id=user_message["id"],
    )
    iterable, metadata = get_agent_runtime_service().stream(message_text, thread_id)

    def _sse(event_name: str, data: Dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def event_stream():
        event_index = 2
        answer_parts: List[str] = []
        yield _sse("run_started", {"run_id": run_id, "thread_id": thread_id})
        for raw_event in iterable:
            mode, event_payload = get_agent_runtime_service().split_event(raw_event)
            if mode != "custom" or not isinstance(event_payload, dict):
                continue
            if event_payload.get("event") == "messages":
                chunk = str(event_payload.get("content") or "")
                if not chunk:
                    continue
                answer_parts.append(chunk)
                yield _sse(
                    "message_chunk",
                    {"run_id": run_id, "thread_id": thread_id, "content": chunk},
                )
                continue
            if event_payload.get("event") == "process":
                mapped = store.save_run_event(
                    thread_id=thread_id,
                    run_id=run_id,
                    event_index=event_index,
                    event_type=str(event_payload.get("event_type") or "process"),
                    title=str(event_payload.get("title") or ""),
                    summary=str(event_payload.get("summary") or ""),
                    status=str(event_payload.get("status") or "info"),
                    payload=event_payload.get("payload")
                    if isinstance(event_payload.get("payload"), dict)
                    else {},
                    message_id=user_message["id"],
                )
                event_index += 1
                yield _sse("process", mapped)
        answer_text = "".join(answer_parts).strip()
        assistant_message = store.save_message(
            thread_id=thread_id,
            role="assistant",
            content={"text": answer_text},
            metadata={"run_id": run_id, "agent_metadata": metadata},
        )
        store.update_thread(user["id"], thread_id, status="idle")
        store.save_run_event(
            thread_id=thread_id,
            run_id=run_id,
            event_index=event_index,
            event_type="message_completed",
            title="回答完成",
            summary=answer_text[:120],
            status="completed",
            payload={"assistant_message_id": assistant_message["id"]},
            message_id=assistant_message["id"],
        )
        yield _sse(
            "message_completed",
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "message": assistant_message,
                "metadata": metadata,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _store_artifact_file(
    *,
    sandbox_run_id: str,
    thread_id: Optional[str],
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    """将 OpenSandbox 产物写到本地磁盘并返回元数据。"""
    decoded = artifact.get("content_bytes") or b""
    if not isinstance(decoded, (bytes, bytearray)):
        decoded = b""
    ext = Path(str(artifact.get("title") or "artifact.bin")).suffix or ".bin"
    dir_path = cfg.artifact_root / (thread_id or "standalone") / sandbox_run_id
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{uuid.uuid4().hex}{ext}"
    file_path.write_bytes(decoded)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return {
        "title": str(artifact.get("title") or file_path.name),
        "artifact_type": "image" if mime_type.startswith("image/") else "file",
        "mime_type": mime_type,
        "storage_path": str(file_path),
        "size_bytes": len(decoded),
        "sha256": hashlib.sha256(decoded).hexdigest(),
        "metadata": {"sandbox_path": str(artifact.get("path") or "")},
    }


@app.post("/api/threads/{thread_id}/sandbox/python")
def execute_thread_python(
    thread_id: str,
    payload: SandboxExecuteRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """供前端直接发起的 Python 执行接口。"""
    store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    return _run_python_execution(
        payload=payload,
        thread_id=thread_id,
        user_id=user["id"],
        message_id=payload.message_id or None,
    )


@app.post("/internal/sandbox/python")
def execute_internal_python(
    payload: SandboxExecuteRequest,
    _: None = Depends(require_service_token),
) -> Dict[str, Any]:
    """供 agent MCP 工具调用的内部沙箱接口。"""
    return _run_python_execution(
        payload=payload,
        thread_id=payload.thread_id or None,
        user_id=None,
        message_id=payload.message_id or None,
    )


def _run_python_execution(
    *,
    payload: SandboxExecuteRequest,
    thread_id: Optional[str],
    user_id: Optional[str],
    message_id: Optional[str],
) -> Dict[str, Any]:
    """统一执行 OpenSandbox Python 任务。"""
    sandbox_run_id = store.create_sandbox_run(
        thread_id=thread_id,
        message_id=message_id,
        user_id=user_id,
        task=payload.task,
        code=payload.code,
        metadata={"trace_id": payload.trace_id, "run_id": payload.run_id},
    )
    result = sandbox_provider.execute_python(
        code=payload.code,
        packages=payload.packages,
        timeout_seconds=payload.timeout_seconds,
    )
    store.finish_sandbox_run(
        run_id=sandbox_run_id,
        opensandbox_sandbox_id=str(result.get("sandbox_id") or ""),
        status="completed" if not result.get("stderr") else "completed_with_stderr",
        stdout_text=str(result.get("stdout") or ""),
        stderr_text=str(result.get("stderr") or ""),
        exit_code=result.get("exit_code"),
    )
    persisted_artifacts: List[Dict[str, Any]] = []
    for artifact in result.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        stored = _store_artifact_file(
            sandbox_run_id=sandbox_run_id,
            thread_id=thread_id,
            artifact=artifact,
        )
        persisted_artifacts.append(
            store.create_artifact(
                thread_id=thread_id,
                message_id=message_id,
                sandbox_run_id=sandbox_run_id,
                title=stored["title"],
                artifact_type=stored["artifact_type"],
                mime_type=stored["mime_type"],
                storage_path=stored["storage_path"],
                size_bytes=stored["size_bytes"],
                sha256=stored["sha256"],
                metadata=stored["metadata"],
            )
        )
    return {
        "sandbox_run_id": sandbox_run_id,
        "stdout": str(result.get("stdout") or ""),
        "stderr": str(result.get("stderr") or ""),
        "exit_code": result.get("exit_code"),
        "artifacts": persisted_artifacts,
        "code": payload.code,
    }


@app.get("/api/artifacts/{artifact_id}/meta")
def artifact_meta(artifact_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """读取 artifact 元数据。"""
    artifact = store.get_artifact(artifact_id)
    thread_id = artifact.get("thread_id")
    if not thread_id:
        raise HTTPException(status_code=404, detail="产物未绑定公开线程")
    store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    return {"artifact": artifact}


@app.get("/api/artifacts/{artifact_id}/content")
def artifact_content(artifact_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> FileResponse:
    """下载 artifact 内容。"""
    artifact = store.get_artifact(artifact_id)
    thread_id = artifact.get("thread_id")
    if not thread_id:
        raise HTTPException(status_code=404, detail="产物未绑定公开线程")
    store.get_thread(owner_user_id=user["id"], thread_id=thread_id)
    return FileResponse(
        path=str(artifact["storage_path"]),
        media_type=str(artifact["mime_type"] or "application/octet-stream"),
        filename=Path(str(artifact["storage_path"])).name,
    )
