"""OpenSandbox 最小联调脚本。

按官方示例创建 code interpreter 沙箱，执行 Python，并验证文件写入。
"""

from __future__ import annotations

from datetime import timedelta
import os

from code_interpreter.models.code import SupportedLanguage
from code_interpreter.sync.code_interpreter import CodeInterpreterSync
from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.models.filesystem import WriteEntry
from opensandbox.sync.sandbox import SandboxSync


def main() -> None:
    """执行最小 smoke test。"""
    domain = os.environ.get("OPENSANDBOX_DOMAIN", "127.0.0.1:8080")
    api_key = os.environ.get("OPENSANDBOX_API_KEY") or None
    template = os.environ.get(
        "OPENSANDBOX_TEMPLATE",
        "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2",
    )
    python_version = os.environ.get("OPENSANDBOX_PYTHON_VERSION", "3.11")
    connection = ConnectionConfigSync(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(minutes=10),
        use_server_proxy=True,
    )
    sandbox = SandboxSync.create(
        template,
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        env={"PYTHON_VERSION": python_version},
        timeout=timedelta(minutes=10),
        connection_config=connection,
    )
    try:
        print("domain:", domain)
        print("template:", template)
        print("sandbox_id:", sandbox.id)
        shell_result = sandbox.commands.run("echo 'Hello OpenSandbox!'")
        print("shell:", shell_result.logs.stdout[0].text.strip())

        sandbox.files.write_files(
            [WriteEntry(path="/tmp/hello.txt", data="Hello World", mode=0o644)]
        )
        content = sandbox.files.read_file("/tmp/hello.txt")
        print("file:", content)

        interpreter = CodeInterpreterSync.create(sandbox)
        result = interpreter.codes.run(
            """
import sys
print(sys.version.split()[0])
value = 2 + 2
value
""",
            language=SupportedLanguage.PYTHON,
        )
        stdout = "\n".join(
            str(item.text or "") for item in result.logs.stdout or []
        ).strip()
        print("stdout:", stdout)
        if result.result:
            print("result:", result.result[0].text.strip())
    finally:
        sandbox.kill()
        sandbox.close()


if __name__ == "__main__":
    main()
