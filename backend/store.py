"""产品后端数据库访问。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import create_engine, text


class BackendStore:
    """统一封装产品后端表结构与 CRUD。"""

    def __init__(self, postgres_url: str) -> None:
        self.engine = create_engine(postgres_url)
        self.text = text

    def init_tables(self) -> None:
        """初始化产品后端需要的表结构。"""
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS app_users (
                        id UUID PRIMARY KEY,
                        login_name TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_login_at TIMESTAMPTZ NULL
                    );
                    """
                )
            )
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS app_auth_sessions (
                        id UUID PRIMARY KEY,
                        user_id UUID NOT NULL,
                        session_token_hash TEXT NOT NULL UNIQUE,
                        user_agent TEXT NOT NULL DEFAULT '',
                        ip_address TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
            )
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS agent_threads (
                        thread_id UUID PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        status TEXT NOT NULL DEFAULT 'idle',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    );
                    """
                )
            )
            conn.execute(
                self.text("ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL;")
            )
            conn.execute(
                self.text("ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS title TEXT NULL;")
            )
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS thread_messages (
                        id UUID PRIMARY KEY,
                        thread_id UUID NOT NULL,
                        role TEXT NOT NULL,
                        content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            )
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS thread_run_events (
                        id UUID PRIMARY KEY,
                        thread_id UUID NOT NULL,
                        message_id UUID NULL,
                        run_id UUID NOT NULL,
                        event_type TEXT NOT NULL,
                        event_index INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'info',
                        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            )
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS sandbox_runs (
                        id UUID PRIMARY KEY,
                        thread_id UUID NULL,
                        message_id UUID NULL,
                        user_id UUID NULL,
                        opensandbox_sandbox_id TEXT NULL,
                        task TEXT NOT NULL DEFAULT '',
                        code TEXT NOT NULL DEFAULT '',
                        language TEXT NOT NULL DEFAULT 'python',
                        status TEXT NOT NULL DEFAULT 'pending',
                        stdout_text TEXT NOT NULL DEFAULT '',
                        stderr_text TEXT NOT NULL DEFAULT '',
                        exit_code INTEGER NULL,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMPTZ NULL
                    );
                    """
                )
            )
            conn.execute(
                self.text(
                    """
                    CREATE TABLE IF NOT EXISTS thread_artifacts (
                        id UUID PRIMARY KEY,
                        thread_id UUID NULL,
                        message_id UUID NULL,
                        sandbox_run_id UUID NULL,
                        title TEXT NOT NULL,
                        artifact_type TEXT NOT NULL DEFAULT 'file',
                        mime_type TEXT NOT NULL,
                        storage_path TEXT NOT NULL,
                        size_bytes BIGINT NOT NULL DEFAULT 0,
                        sha256 TEXT NOT NULL DEFAULT '',
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            )

    @staticmethod
    def _row_to_dict(row: Any, keys: List[str]) -> Dict[str, Any]:
        """将查询结果统一转成字典。"""
        return {key: row[idx] for idx, key in enumerate(keys)}

    def create_user(self, login_name: str, password_hash: str, display_name: str) -> Dict[str, Any]:
        """创建用户。"""
        user_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            exists = conn.execute(
                self.text("SELECT 1 FROM app_users WHERE login_name = :login_name"),
                {"login_name": login_name},
            ).fetchone()
            if exists:
                raise HTTPException(status_code=409, detail="用户已存在")
            conn.execute(
                self.text(
                    """
                    INSERT INTO app_users (id, login_name, password_hash, display_name)
                    VALUES (:id, :login_name, :password_hash, :display_name)
                    """
                ),
                {
                    "id": user_id,
                    "login_name": login_name,
                    "password_hash": password_hash,
                    "display_name": display_name,
                },
            )
        return self.get_user_by_id(user_id)

    def get_user_by_login_name(self, login_name: str) -> Optional[Dict[str, Any]]:
        """按登录名查询用户。"""
        with self.engine.begin() as conn:
            row = conn.execute(
                self.text(
                    """
                    SELECT id::text, login_name, password_hash, display_name, status, created_at, last_login_at
                    FROM app_users WHERE login_name = :login_name
                    """
                ),
                {"login_name": login_name},
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(
            row,
            ["id", "login_name", "password_hash", "display_name", "status", "created_at", "last_login_at"],
        )

    def get_user_by_id(self, user_id: str) -> Dict[str, Any]:
        """按 ID 查询用户。"""
        with self.engine.begin() as conn:
            row = conn.execute(
                self.text(
                    """
                    SELECT id::text, login_name, password_hash, display_name, status, created_at, last_login_at
                    FROM app_users WHERE id = :id
                    """
                ),
                {"id": user_id},
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        return self._row_to_dict(
            row,
            ["id", "login_name", "password_hash", "display_name", "status", "created_at", "last_login_at"],
        )

    def touch_last_login(self, user_id: str, login_at: datetime) -> None:
        """更新最近登录时间。"""
        with self.engine.begin() as conn:
            conn.execute(
                self.text("UPDATE app_users SET last_login_at = :login_at WHERE id = :id"),
                {"id": user_id, "login_at": login_at},
            )

    def create_session(
        self,
        *,
        user_id: str,
        session_token_hash: str,
        expires_at: datetime,
        user_agent: str,
        ip_address: str,
    ) -> Dict[str, Any]:
        """创建登录会话。"""
        session_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    INSERT INTO app_auth_sessions (
                        id, user_id, session_token_hash, user_agent, ip_address, expires_at
                    )
                    VALUES (
                        :id, :user_id, :session_token_hash, :user_agent, :ip_address, :expires_at
                    )
                    """
                ),
                {
                    "id": session_id,
                    "user_id": user_id,
                    "session_token_hash": session_token_hash,
                    "user_agent": user_agent,
                    "ip_address": ip_address,
                    "expires_at": expires_at,
                },
            )
        return {
            "id": session_id,
            "user_id": user_id,
            "expires_at": expires_at,
        }

    def get_user_by_session_token_hash(self, session_token_hash: str) -> Optional[Dict[str, Any]]:
        """按 session token 查询用户。"""
        with self.engine.begin() as conn:
            row = conn.execute(
                self.text(
                    """
                    SELECT
                        u.id::text,
                        u.login_name,
                        u.password_hash,
                        u.display_name,
                        u.status,
                        u.created_at,
                        u.last_login_at,
                        s.expires_at
                    FROM app_auth_sessions s
                    JOIN app_users u ON u.id = s.user_id
                    WHERE s.session_token_hash = :session_token_hash
                    """
                ),
                {"session_token_hash": session_token_hash},
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(
            row,
            ["id", "login_name", "password_hash", "display_name", "status", "created_at", "last_login_at", "expires_at"],
        )

    def delete_session(self, session_token_hash: str) -> None:
        """删除会话。"""
        with self.engine.begin() as conn:
            conn.execute(
                self.text("DELETE FROM app_auth_sessions WHERE session_token_hash = :session_token_hash"),
                {"session_token_hash": session_token_hash},
            )

    def create_thread(
        self,
        *,
        owner_user_id: str,
        title: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建产品线程。"""
        thread_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    INSERT INTO agent_threads (thread_id, owner_user_id, title, status, metadata)
                    VALUES (:thread_id, :owner_user_id, :title, 'idle', CAST(:metadata AS jsonb))
                    """
                ),
                {
                    "thread_id": thread_id,
                    "owner_user_id": owner_user_id,
                    "title": title,
                    "metadata": json.dumps(metadata or {}),
                },
            )
        return self.get_thread(owner_user_id=owner_user_id, thread_id=thread_id)

    def list_threads(self, owner_user_id: str) -> List[Dict[str, Any]]:
        """列出用户自己的线程。"""
        with self.engine.begin() as conn:
            rows = conn.execute(
                self.text(
                    """
                    SELECT thread_id::text, owner_user_id::text, title, status, metadata, created_at, updated_at
                    FROM agent_threads
                    WHERE owner_user_id = :owner_user_id
                    ORDER BY updated_at DESC
                    """
                ),
                {"owner_user_id": owner_user_id},
            ).fetchall()
        return [
            self._row_to_dict(
                row,
                ["thread_id", "owner_user_id", "title", "status", "metadata", "created_at", "updated_at"],
            )
            for row in rows
        ]

    def get_thread(self, *, owner_user_id: str, thread_id: str) -> Dict[str, Any]:
        """读取用户线程。"""
        with self.engine.begin() as conn:
            row = conn.execute(
                self.text(
                    """
                    SELECT thread_id::text, owner_user_id::text, title, status, metadata, created_at, updated_at
                    FROM agent_threads
                    WHERE thread_id = :thread_id AND owner_user_id = :owner_user_id
                    """
                ),
                {"thread_id": thread_id, "owner_user_id": owner_user_id},
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="线程不存在")
        return self._row_to_dict(
            row,
            ["thread_id", "owner_user_id", "title", "status", "metadata", "created_at", "updated_at"],
        )

    def update_thread(self, owner_user_id: str, thread_id: str, *, title: Optional[str] = None, status: Optional[str] = None) -> None:
        """更新线程标题或状态。"""
        fields = ["updated_at = NOW()"]
        params: Dict[str, Any] = {"thread_id": thread_id, "owner_user_id": owner_user_id}
        if title is not None:
            fields.append("title = :title")
            params["title"] = title
        if status is not None:
            fields.append("status = :status")
            params["status"] = status
        if len(fields) == 1:
            return
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    f"UPDATE agent_threads SET {', '.join(fields)} WHERE thread_id = :thread_id AND owner_user_id = :owner_user_id"
                ),
                params,
            )

    def delete_thread(self, owner_user_id: str, thread_id: str) -> None:
        """删除线程及其所有关联数据（消息、事件、产物记录）。"""
        with self.engine.begin() as conn:
            # 先验证归属权
            row = conn.execute(
                self.text(
                    "SELECT thread_id FROM agent_threads WHERE thread_id = :thread_id AND owner_user_id = :owner_user_id"
                ),
                {"thread_id": thread_id, "owner_user_id": owner_user_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="会话不存在或无权限")
            # 删除子表数据（无外键约束时需手动清理）
            conn.execute(self.text("DELETE FROM thread_messages WHERE thread_id = :thread_id"), {"thread_id": thread_id})
            conn.execute(self.text("DELETE FROM thread_run_events WHERE thread_id = :thread_id"), {"thread_id": thread_id})
            conn.execute(self.text("DELETE FROM thread_artifacts WHERE thread_id = :thread_id"), {"thread_id": thread_id})
            conn.execute(self.text("DELETE FROM sandbox_runs WHERE thread_id = :thread_id"), {"thread_id": thread_id})
            conn.execute(self.text("DELETE FROM agent_threads WHERE thread_id = :thread_id"), {"thread_id": thread_id})

    def save_message(
        self,
        *,
        thread_id: str,
        role: str,
        content: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """写入产品消息。"""
        message_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    INSERT INTO thread_messages (id, thread_id, role, content_json, metadata_json)
                    VALUES (:id, :thread_id, :role, CAST(:content_json AS jsonb), CAST(:metadata_json AS jsonb))
                    """
                ),
                {
                    "id": message_id,
                    "thread_id": thread_id,
                    "role": role,
                    "content_json": json.dumps(content or {}),
                    "metadata_json": json.dumps(metadata or {}),
                },
            )
            conn.execute(
                self.text("UPDATE agent_threads SET updated_at = NOW() WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            )
        return {
            "id": message_id,
            "thread_id": thread_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }

    def list_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """列出线程消息。"""
        with self.engine.begin() as conn:
            rows = conn.execute(
                self.text(
                    """
                    SELECT id::text, thread_id::text, role, content_json, metadata_json, created_at
                    FROM thread_messages
                    WHERE thread_id = :thread_id
                    ORDER BY created_at ASC
                    """
                ),
                {"thread_id": thread_id},
            ).fetchall()
        return [
            self._row_to_dict(
                row,
                ["id", "thread_id", "role", "content_json", "metadata_json", "created_at"],
            )
            for row in rows
        ]

    def save_run_event(
        self,
        *,
        thread_id: str,
        run_id: str,
        event_index: int,
        event_type: str,
        title: str,
        summary: str,
        status: str,
        payload: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """写入过程事件。"""
        event_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    INSERT INTO thread_run_events (
                        id, thread_id, message_id, run_id, event_type, event_index, title, summary, status, payload_json
                    )
                    VALUES (
                        :id, :thread_id, :message_id, :run_id, :event_type, :event_index, :title, :summary, :status, CAST(:payload_json AS jsonb)
                    )
                    """
                ),
                {
                    "id": event_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "run_id": run_id,
                    "event_type": event_type,
                    "event_index": event_index,
                    "title": title,
                    "summary": summary,
                    "status": status,
                    "payload_json": json.dumps(payload or {}),
                },
            )
        return {
            "id": event_id,
            "run_id": run_id,
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "status": status,
            "payload": payload or {},
        }

    def list_run_events(self, *, thread_id: str, run_id: str) -> List[Dict[str, Any]]:
        """读取某次运行的过程事件。"""
        with self.engine.begin() as conn:
            rows = conn.execute(
                self.text(
                    """
                    SELECT id::text, thread_id::text, message_id::text, run_id::text, event_type, event_index, title, summary, status, payload_json, created_at
                    FROM thread_run_events
                    WHERE thread_id = :thread_id AND run_id = :run_id
                    ORDER BY event_index ASC, created_at ASC
                    """
                ),
                {"thread_id": thread_id, "run_id": run_id},
            ).fetchall()
        return [
            self._row_to_dict(
                row,
                ["id", "thread_id", "message_id", "run_id", "event_type", "event_index", "title", "summary", "status", "payload_json", "created_at"],
            )
            for row in rows
        ]

    def create_sandbox_run(
        self,
        *,
        thread_id: Optional[str],
        message_id: Optional[str],
        user_id: Optional[str],
        task: str,
        code: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """创建沙箱运行记录。"""
        run_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    INSERT INTO sandbox_runs (id, thread_id, message_id, user_id, task, code, metadata_json)
                    VALUES (:id, :thread_id, :message_id, :user_id, :task, :code, CAST(:metadata_json AS jsonb))
                    """
                ),
                {
                    "id": run_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "user_id": user_id,
                    "task": task,
                    "code": code,
                    "metadata_json": json.dumps(metadata or {}),
                },
            )
        return run_id

    def finish_sandbox_run(
        self,
        *,
        run_id: str,
        opensandbox_sandbox_id: str,
        status: str,
        stdout_text: str,
        stderr_text: str,
        exit_code: Optional[int],
    ) -> None:
        """回填沙箱运行结果。"""
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    UPDATE sandbox_runs
                    SET opensandbox_sandbox_id = :opensandbox_sandbox_id,
                        status = :status,
                        stdout_text = :stdout_text,
                        stderr_text = :stderr_text,
                        exit_code = :exit_code,
                        finished_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": run_id,
                    "opensandbox_sandbox_id": opensandbox_sandbox_id,
                    "status": status,
                    "stdout_text": stdout_text,
                    "stderr_text": stderr_text,
                    "exit_code": exit_code,
                },
            )

    def create_artifact(
        self,
        *,
        thread_id: Optional[str],
        message_id: Optional[str],
        sandbox_run_id: Optional[str],
        title: str,
        artifact_type: str,
        mime_type: str,
        storage_path: str,
        size_bytes: int,
        sha256: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建 artifact 元数据。"""
        artifact_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    INSERT INTO thread_artifacts (
                        id, thread_id, message_id, sandbox_run_id, title, artifact_type,
                        mime_type, storage_path, size_bytes, sha256, metadata_json
                    )
                    VALUES (
                        :id, :thread_id, :message_id, :sandbox_run_id, :title, :artifact_type,
                        :mime_type, :storage_path, :size_bytes, :sha256, CAST(:metadata_json AS jsonb)
                    )
                    """
                ),
                {
                    "id": artifact_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "sandbox_run_id": sandbox_run_id,
                    "title": title,
                    "artifact_type": artifact_type,
                    "mime_type": mime_type,
                    "storage_path": storage_path,
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                    "metadata_json": json.dumps(metadata or {}),
                },
            )
        return self.get_artifact(artifact_id)

    def merge_artifact_metadata(self, artifact_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """合并更新 artifact 元数据。"""
        current = self.get_artifact(artifact_id)
        merged: Dict[str, Any] = {}
        if isinstance(current.get("metadata_json"), dict):
            merged.update(current["metadata_json"])
        merged.update(metadata or {})
        with self.engine.begin() as conn:
            conn.execute(
                self.text(
                    """
                    UPDATE thread_artifacts
                    SET metadata_json = CAST(:metadata_json AS jsonb)
                    WHERE id = :id
                    """
                ),
                {
                    "id": artifact_id,
                    "metadata_json": json.dumps(merged),
                },
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        """读取 artifact 元数据。"""
        with self.engine.begin() as conn:
            row = conn.execute(
                self.text(
                    """
                    SELECT id::text, thread_id::text, message_id::text, sandbox_run_id::text, title,
                           artifact_type, mime_type, storage_path, size_bytes, sha256, metadata_json, created_at
                    FROM thread_artifacts
                    WHERE id = :id
                    """
                ),
                {"id": artifact_id},
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="产物不存在")
        return self._row_to_dict(
            row,
            ["id", "thread_id", "message_id", "sandbox_run_id", "title", "artifact_type", "mime_type", "storage_path", "size_bytes", "sha256", "metadata_json", "created_at"],
        )

    def list_thread_artifacts(self, thread_id: str) -> List[Dict[str, Any]]:
        """列出线程下的 artifact。"""
        with self.engine.begin() as conn:
            rows = conn.execute(
                self.text(
                    """
                    SELECT id::text, thread_id::text, message_id::text, sandbox_run_id::text, title,
                           artifact_type, mime_type, storage_path, size_bytes, sha256, metadata_json, created_at
                    FROM thread_artifacts
                    WHERE thread_id = :thread_id
                    ORDER BY created_at DESC
                    """
                ),
                {"thread_id": thread_id},
            ).fetchall()
        return [
            self._row_to_dict(
                row,
                ["id", "thread_id", "message_id", "sandbox_run_id", "title", "artifact_type", "mime_type", "storage_path", "size_bytes", "sha256", "metadata_json", "created_at"],
            )
            for row in rows
        ]
