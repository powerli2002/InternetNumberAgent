"""OpenSandbox 执行适配器。"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List

import httpx

from backend.config import BackendConfig


class OpenSandboxProvider:
    """基于官方 OpenSandbox + Code Interpreter SDK 的同步执行器。"""

    def __init__(self, config: BackendConfig) -> None:
        self.config = config

    def execute_python(
        self,
        *,
        code: str,
        input_data: Dict[str, Any],
        input_files: List[Dict[str, Any]],
        packages: List[str],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """在 OpenSandbox 中执行 Python，并收集 stdout/stderr/产物。"""
        try:
            from opensandbox.config.connection_sync import ConnectionConfigSync  # type: ignore
            from opensandbox.models.filesystem import SearchEntry, WriteEntry  # type: ignore
            from opensandbox.sync.sandbox import SandboxSync  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "未安装 OpenSandbox 官方 SDK。请安装 opensandbox、opensandbox-server、opensandbox-code-interpreter。"
            ) from exc

        connection_config = ConnectionConfigSync(
            domain=self.config.opensandbox_domain,
            api_key=self.config.opensandbox_api_key,
            request_timeout=timedelta(seconds=max(60, timeout_seconds)),
            transport=httpx.HTTPTransport(limits=httpx.Limits(max_connections=20)),
            use_server_proxy=True,
        )

        sandbox = SandboxSync.create(
            self.config.opensandbox_template,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            env={"PYTHON_VERSION": self.config.opensandbox_python_version},
            timeout=timedelta(seconds=max(30, timeout_seconds)),
            connection_config=connection_config,
        )

        try:
            def _read_execution_logs(execution: Any, stream: str) -> str:
                """提取命令执行日志，统一收敛 stdout/stderr 文本。"""
                return "\n".join(
                    str(getattr(item, "text", "") or "")
                    for item in getattr(getattr(execution, "logs", None), stream, []) or []
                ).strip()

            input_paths = [
                str(item.get("path") or "").strip()
                for item in (input_files or [])
                if isinstance(item, dict) and str(item.get("path") or "").strip()
            ]
            mkdir_targets = {"/workspace/artifacts", "/workspace/input"}
            for path in input_paths:
                parent = str(Path(path).parent)
                if parent:
                    mkdir_targets.add(parent)
            sandbox.commands.run(
                "mkdir -p " + " ".join(sorted(mkdir_targets))
            )
            write_entries = [
                WriteEntry(path="/workspace/main.py", data=code, mode=0o644),
                WriteEntry(
                    path="/workspace/input/input.json",
                    data=json.dumps(input_data or {}, ensure_ascii=False, indent=2),
                    mode=0o644,
                ),
            ]
            for item in input_files or []:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                if not path:
                    continue
                write_entries.append(
                    WriteEntry(
                        path=path,
                        data=str(item.get("content") or ""),
                        mode=0o644,
                    )
                )
            sandbox.files.write_files(write_entries)
            install_stdout = ""
            if packages:
                install_cmd = "python3 -m pip install " + " ".join(packages)
                install_result = sandbox.commands.run(f"cd /workspace && {install_cmd}")
                install_stdout = _read_execution_logs(install_result, "stdout")
                install_stderr = _read_execution_logs(install_result, "stderr")
                install_exit_code = getattr(install_result, "exit_code", None)
                if install_exit_code not in (None, 0):
                    detail = install_stderr or install_stdout or f"exit_code={install_exit_code}"
                    raise RuntimeError("Python 依赖安装失败: " + detail)

            result = sandbox.commands.run("cd /workspace && python3 /workspace/main.py")
            stdout = _read_execution_logs(result, "stdout")
            stderr = _read_execution_logs(result, "stderr")
            exit_code = getattr(result, "exit_code", None)

            artifacts: List[Dict[str, Any]] = []
            for entry in sandbox.files.search(
                SearchEntry(path="/workspace/artifacts", pattern="*")
            ):
                artifact_path = str(getattr(entry, "path", "") or "")
                if not artifact_path:
                    continue
                raw = sandbox.files.read_bytes(artifact_path)
                artifacts.append(
                    {
                        "path": artifact_path,
                        "title": Path(artifact_path).name,
                        "content_bytes": raw,
                        "size_bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )

            return {
                "sandbox_id": sandbox.id,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": int(exit_code) if exit_code is not None else None,
                "artifacts": artifacts,
                "install_stdout": install_stdout if packages else "",
            }
        finally:
            try:
                sandbox.kill()
            finally:
                sandbox.close()
