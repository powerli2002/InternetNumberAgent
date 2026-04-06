"""OpenSandbox 执行适配器。"""

from __future__ import annotations

import hashlib
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
        packages: List[str],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """在 OpenSandbox 中执行 Python，并收集 stdout/stderr/产物。"""
        try:
            from code_interpreter.models.code import SupportedLanguage  # type: ignore
            from code_interpreter.sync.code_interpreter import CodeInterpreterSync  # type: ignore
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
        )

        sandbox = SandboxSync.create(
            self.config.opensandbox_template,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            env={"PYTHON_VERSION": self.config.opensandbox_python_version},
            timeout=timedelta(seconds=max(30, timeout_seconds)),
            connection_config=connection_config,
        )

        try:
            sandbox.commands.run("mkdir -p /workspace/artifacts")
            sandbox.files.write_files(
                [
                    WriteEntry(path="/workspace/main.py", data=code, mode=0o644),
                ]
            )
            if packages:
                install_cmd = "pip install " + " ".join(packages)
                sandbox.commands.run(f"cd /workspace && {install_cmd}")

            interpreter = CodeInterpreterSync.create(sandbox=sandbox)
            result = interpreter.codes.run(
                code,
                language=SupportedLanguage.PYTHON,
            )
            stdout = "\n".join(
                str(getattr(item, "text", "") or "")
                for item in getattr(getattr(result, "logs", None), "stdout", []) or []
            ).strip()
            stderr = "\n".join(
                str(getattr(item, "text", "") or "")
                for item in getattr(getattr(result, "logs", None), "stderr", []) or []
            ).strip()

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
                "exit_code": 0 if not stderr else None,
                "artifacts": artifacts,
            }
        finally:
            try:
                sandbox.kill()
            finally:
                sandbox.close()
