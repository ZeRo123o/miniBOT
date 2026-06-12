from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class SandboxRecord:
    sandbox_id: str
    sandbox_url: str
    status: str | None = None


class ProvisionerClient:
    """访问独立 sandbox-provisioner 的轻量 HTTP 客户端。"""

    def __init__(self, base_url: str, token: str, *, timeout_seconds: int = 30):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if self._token:
            headers["X-Sandbox-Token"] = self._token
        return httpx.request(
            method,
            f"{self._base_url}{path}",
            headers=headers,
            timeout=self._timeout,
            **kwargs,
        )

    def create(
        self,
        *,
        sandbox_id: str,
        user_segment: str,
        conversation_id: int,
        env: dict[str, str] | None = None,
    ) -> SandboxRecord:
        response = self._request(
            "POST",
            "/api/sandboxes",
            json={
                "sandbox_id": sandbox_id,
                "user_segment": user_segment,
                "conversation_id": conversation_id,
                "env": env or {},
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"failed to create sandbox {sandbox_id}: "
                f"{response.status_code} {response.text}"
            )
        payload = response.json()
        return SandboxRecord(
            sandbox_id=payload["sandbox_id"],
            sandbox_url=payload["sandbox_url"],
            status=payload.get("status"),
        )

    def discover(self, sandbox_id: str) -> SandboxRecord | None:
        response = self._request("GET", f"/api/sandboxes/{sandbox_id}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RuntimeError(
                f"failed to discover sandbox {sandbox_id}: "
                f"{response.status_code} {response.text}"
            )
        payload = response.json()
        return SandboxRecord(
            sandbox_id=payload["sandbox_id"],
            sandbox_url=payload["sandbox_url"],
            status=payload.get("status"),
        )

    def touch(self, sandbox_id: str) -> bool:
        response = self._request("POST", f"/api/sandboxes/{sandbox_id}/touch")
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise RuntimeError(
                f"failed to touch sandbox {sandbox_id}: "
                f"{response.status_code} {response.text}"
            )
        return True

    def delete(self, sandbox_id: str) -> None:
        response = self._request("DELETE", f"/api/sandboxes/{sandbox_id}")
        if response.status_code not in {200, 404}:
            raise RuntimeError(
                f"failed to delete sandbox {sandbox_id}: "
                f"{response.status_code} {response.text}"
            )


class AgentSandbox:
    """把 agent-sandbox SDK 收敛为 miniBOT 使用的文件接口。"""

    def __init__(self, sandbox_id: str, sandbox_url: str, timeout_seconds: int):
        try:
            from agent_sandbox import Sandbox as AgentSandboxClient
        except ImportError as exc:
            raise RuntimeError(
                "agent-sandbox dependency is required for sandbox tools"
            ) from exc
        self.id = sandbox_id
        self.url = sandbox_url
        self._client = AgentSandboxClient(
            base_url=sandbox_url,
            timeout=timeout_seconds,
        )

    def read_text(self, path: str) -> str:
        result = self._client.file.read_file(file=path)
        content = result.data.content
        if content is None:
            return ""
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return str(content)

    def write_text(self, path: str, content: str) -> None:
        result = self._client.file.write_file(file=path, content=content)
        if not result.success:
            raise RuntimeError(result.message or f"failed to write {path}")

    def list_path(self, path: str) -> list[dict[str, Any]]:
        result = self._client.file.list_path(
            path=path,
            recursive=False,
            include_size=True,
        )
        return [
            {
                "path": item.path,
                "is_dir": bool(item.is_directory),
                "size": item.size if isinstance(item.size, int) else None,
            }
            for item in (result.data.files or [])
        ]

    def find_files(self, path: str, pattern: str) -> list[str]:
        result = self._client.file.find_files(path=path, glob=pattern)
        return list(result.data.files or [])
