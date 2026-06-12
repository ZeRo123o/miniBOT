from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib import request

import docker
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("sandbox-provisioner")

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class CreateSandboxRequest(BaseModel):
    sandbox_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    user_segment: str = Field(pattern=r"^user-[a-f0-9]{12}$")
    conversation_id: int = Field(gt=0)
    env: dict[str, str] = Field(default_factory=dict)


class SandboxResponse(BaseModel):
    sandbox_id: str
    sandbox_url: str
    status: str


@dataclass(slots=True)
class SandboxRecord:
    sandbox_id: str
    sandbox_url: str
    status: str


def require_internal_token(
    x_sandbox_token: str | None = Header(default=None),
) -> None:
    expected = os.getenv("SANDBOX_INTERNAL_TOKEN", "")
    if not expected or x_sandbox_token != expected:
        raise HTTPException(status_code=401, detail="invalid sandbox token")


def wait_until_ready(url: str, timeout_seconds: int) -> bool:
    opener = request.build_opener(request.ProxyHandler({}))
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with opener.open(f"{url.rstrip('/')}/v1/sandbox", timeout=3) as response:
                if getattr(response, "status", 200) == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


class DockerSandboxManager:
    """创建、校验和销毁受 miniBOT 管理的沙盒容器。"""

    def __init__(self) -> None:
        self._client = docker.from_env()
        try:
            self._client.ping()
        except DockerException as exc:
            raise RuntimeError(f"Docker daemon unavailable: {exc}") from exc

        self._lock = threading.Lock()
        self._image = os.getenv(
            "SANDBOX_IMAGE",
            "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest",
        )
        self._container_port = int(os.getenv("SANDBOX_CONTAINER_PORT", "8080"))
        self._prefix = os.getenv("SANDBOX_CONTAINER_PREFIX", "minibot-sandbox")
        self._advertise_host = os.getenv("SANDBOX_ADVERTISE_HOST", "localhost")
        self._health_host = os.getenv("SANDBOX_HEALTH_HOST", "host.docker.internal")
        self._bind_host = os.getenv("SANDBOX_BIND_HOST", "127.0.0.1")
        self._network = os.getenv("SANDBOX_DOCKER_NETWORK", "")
        self._health_timeout = int(os.getenv("SANDBOX_HEALTH_TIMEOUT_SECONDS", "120"))
        self._runtime_host_root = self._resolve_runtime_host_root()

    def _resolve_runtime_host_root(self) -> Path:
        configured = os.getenv("SANDBOX_RUNTIME_HOST_PATH", "").strip()
        if configured:
            return Path(self._normalize_docker_host_path(configured))

        container_id = os.getenv("HOSTNAME", "").strip()
        if not container_id:
            raise RuntimeError("HOSTNAME is required to infer runtime host path")
        inspected = self._client.api.inspect_container(container_id)
        for mount in inspected.get("Mounts") or []:
            if str(mount.get("Destination") or "").rstrip("/") == "/app/runtime":
                source = str(mount.get("Source") or "")
                return Path(self._normalize_docker_host_path(source))
        raise RuntimeError("cannot infer host source for /app/runtime")

    @staticmethod
    def _normalize_docker_host_path(value: str) -> str:
        normalized = value.replace("\\", "/")
        match = re.match(r"^([A-Za-z]):/(.+)$", normalized)
        if match:
            return (
                f"/run/desktop/mnt/host/{match.group(1).lower()}/"
                f"{match.group(2).lstrip('/')}"
            )
        return normalized

    def _container_name(self, sandbox_id: str) -> str:
        return f"{self._prefix}-{sandbox_id}"

    def _container(self, sandbox_id: str):
        try:
            return self._client.containers.get(self._container_name(sandbox_id))
        except NotFound:
            return None

    def _scope_paths(
        self,
        user_segment: str,
        conversation_id: int,
    ) -> dict[str, Path]:
        if not SAFE_SEGMENT.fullmatch(user_segment):
            raise ValueError("invalid user segment")
        user_root = self._runtime_host_root / "users" / user_segment
        conversation_root = user_root / "conversations" / str(conversation_id)
        paths = {
            "workspace": user_root / "workspace",
            "uploads": conversation_root / "uploads",
            "outputs": conversation_root / "outputs",
            "skills": conversation_root / "skills",
        }
        runtime_root = self._runtime_host_root.resolve()
        for path in paths.values():
            resolved = path.resolve()
            try:
                resolved.relative_to(runtime_root)
            except ValueError as exc:
                raise ValueError("sandbox mount escaped runtime root") from exc
            resolved.mkdir(parents=True, exist_ok=True)
        return paths

    def _record(self, container, sandbox_id: str, *, health: bool = False) -> SandboxRecord:
        container.reload()
        if health and self._network:
            return SandboxRecord(
                sandbox_id=sandbox_id,
                sandbox_url=(
                    f"http://{container.name}:{self._container_port}"
                ),
                status=container.status,
            )
        bindings = (
            (container.attrs.get("NetworkSettings") or {})
            .get("Ports", {})
            .get(f"{self._container_port}/tcp")
            or []
        )
        if not bindings or not bindings[0].get("HostPort"):
            raise RuntimeError(f"sandbox {sandbox_id} has no published port")
        port = int(bindings[0]["HostPort"])
        host = self._health_host if health else self._advertise_host
        return SandboxRecord(
            sandbox_id=sandbox_id,
            sandbox_url=f"http://{host}:{port}",
            status=container.status,
        )

    @staticmethod
    def _ensure_writable_mounts(container) -> None:
        """只给 Agent 需要写入的两个挂载目录补充写权限。"""
        result = container.exec_run(
            [
                "sh",
                "-lc",
                "chmod -R a+rwx /mnt/user-data/workspace "
                "/mnt/user-data/outputs",
            ],
            user="0:0",
        )
        if result.exit_code != 0:
            output = (
                result.output.decode("utf-8", errors="ignore")
                if isinstance(result.output, bytes)
                else str(result.output)
            )
            raise RuntimeError(f"failed to prepare writable mounts: {output}")

    def create(self, payload: CreateSandboxRequest) -> SandboxRecord:
        with self._lock:
            expected_labels = {
                "minibot.user-segment": payload.user_segment,
                "minibot.conversation-id": str(payload.conversation_id),
            }
            existing = self._container(payload.sandbox_id)
            if existing is not None:
                existing.reload()
                labels = existing.labels or {}
                identity_matches = all(
                    labels.get(key) == value
                    for key, value in expected_labels.items()
                )
                if identity_matches and existing.status == "running":
                    self._ensure_writable_mounts(existing)
                    health_record = self._record(
                        existing,
                        payload.sandbox_id,
                        health=True,
                    )
                    if wait_until_ready(health_record.sandbox_url, 5):
                        return self._record(existing, payload.sandbox_id)
                self.delete(payload.sandbox_id)

            paths = self._scope_paths(
                payload.user_segment,
                payload.conversation_id,
            )
            run_kwargs = {
                "name": self._container_name(payload.sandbox_id),
                "detach": True,
                "remove": True,
                "labels": {
                    "app": "minibot-sandbox",
                    "managed-by": "minibot-sandbox-provisioner",
                    "minibot.sandbox-id": payload.sandbox_id,
                    **expected_labels,
                },
                "volumes": {
                    str(paths["workspace"]): {
                        "bind": "/mnt/user-data/workspace",
                        "mode": "rw",
                    },
                    str(paths["uploads"]): {
                        "bind": "/mnt/user-data/uploads",
                        "mode": "ro",
                    },
                    str(paths["outputs"]): {
                        "bind": "/mnt/user-data/outputs",
                        "mode": "rw",
                    },
                    str(paths["skills"]): {
                        "bind": "/mnt/skills",
                        "mode": "ro",
                    },
                },
                "ports": {
                    f"{self._container_port}/tcp": (self._bind_host, None),
                },
                "environment": {
                    str(key): str(value)
                    for key, value in payload.env.items()
                },
                # 上游镜像启动时需要创建 gem 用户，保留默认最小能力集合，
                # 仅移除文件工具场景不需要的原始网络和设备节点能力。
                "cap_drop": ["NET_RAW", "MKNOD"],
                "security_opt": ["no-new-privileges:true"],
                "pids_limit": int(os.getenv("SANDBOX_PIDS_LIMIT", "256")),
                "mem_limit": os.getenv("SANDBOX_MEMORY_LIMIT", "1g"),
                "nano_cpus": int(float(os.getenv("SANDBOX_CPU_LIMIT", "1")) * 1_000_000_000),
                "tmpfs": {
                    "/tmp": "rw,noexec,nosuid,size=256m",
                    "/home/gem": "rw,exec,nosuid,size=512m",
                },
            }
            if self._network:
                run_kwargs["network"] = self._network

            container = self._client.containers.run(self._image, **run_kwargs)
            self._ensure_writable_mounts(container)
            health_record = self._record(
                container,
                payload.sandbox_id,
                health=True,
            )
            if not wait_until_ready(
                health_record.sandbox_url,
                self._health_timeout,
            ):
                self.delete(payload.sandbox_id)
                raise RuntimeError(
                    f"sandbox {payload.sandbox_id} failed health check"
                )
            return self._record(container, payload.sandbox_id)

    def discover(self, sandbox_id: str) -> SandboxRecord | None:
        container = self._container(sandbox_id)
        if container is None:
            return None
        container.reload()
        if container.status != "running":
            return None
        labels = container.labels or {}
        if labels.get("managed-by") != "minibot-sandbox-provisioner":
            return None
        health_record = self._record(container, sandbox_id, health=True)
        if not wait_until_ready(health_record.sandbox_url, 5):
            return None
        return self._record(container, sandbox_id)

    def list(self) -> list[SandboxRecord]:
        containers = self._client.containers.list(
            all=True,
            filters={
                "label": [
                    "app=minibot-sandbox",
                    "managed-by=minibot-sandbox-provisioner",
                ]
            },
        )
        records = []
        for container in containers:
            sandbox_id = (container.labels or {}).get("minibot.sandbox-id")
            if sandbox_id and container.status == "running":
                records.append(self._record(container, sandbox_id))
        return records

    def delete(self, sandbox_id: str) -> None:
        container = self._container(sandbox_id)
        if container is None:
            return
        container.remove(force=True, v=True)


class IdleReaper:
    def __init__(self, manager: DockerSandboxManager) -> None:
        self._manager = manager
        self._lock = threading.Lock()
        self._last_activity: dict[str, float] = {}
        self._timeout = int(os.getenv("SANDBOX_IDLE_TIMEOUT_SECONDS", "600"))
        self._interval = int(os.getenv("SANDBOX_IDLE_CHECK_INTERVAL_SECONDS", "30"))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def touch(self, sandbox_id: str) -> None:
        with self._lock:
            self._last_activity[sandbox_id] = time.time()

    def forget(self, sandbox_id: str) -> None:
        with self._lock:
            self._last_activity.pop(sandbox_id, None)

    def start(self) -> None:
        now = time.time()
        for record in self._manager.list():
            self._last_activity[record.sandbox_id] = now
        self._thread = threading.Thread(
            target=self._run,
            name="sandbox-idle-reaper",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            cutoff = time.time() - self._timeout
            with self._lock:
                expired = [
                    sandbox_id
                    for sandbox_id, last_activity in self._last_activity.items()
                    if last_activity <= cutoff
                ]
            for sandbox_id in expired:
                try:
                    self._manager.delete(sandbox_id)
                    self.forget(sandbox_id)
                    logger.info("Deleted idle sandbox %s", sandbox_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to delete idle sandbox %s: %s",
                        sandbox_id,
                        exc,
                    )

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)


manager = DockerSandboxManager()
reaper = IdleReaper(manager)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reaper.start()
    try:
        yield
    finally:
        reaper.shutdown()


app = FastAPI(title="miniBOT Sandbox Provisioner", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "backend": "docker"}


@app.post(
    "/api/sandboxes",
    response_model=SandboxResponse,
    dependencies=[Depends(require_internal_token)],
)
def create_sandbox(payload: CreateSandboxRequest):
    try:
        record = manager.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    reaper.touch(record.sandbox_id)
    return SandboxResponse(**asdict(record))


@app.get(
    "/api/sandboxes/{sandbox_id}",
    response_model=SandboxResponse,
    dependencies=[Depends(require_internal_token)],
)
def get_sandbox(sandbox_id: str):
    record = manager.discover(sandbox_id)
    if record is None:
        raise HTTPException(status_code=404, detail="sandbox not found")
    reaper.touch(sandbox_id)
    return SandboxResponse(**asdict(record))


@app.post(
    "/api/sandboxes/{sandbox_id}/touch",
    dependencies=[Depends(require_internal_token)],
)
def touch_sandbox(sandbox_id: str):
    record = manager.discover(sandbox_id)
    if record is None:
        raise HTTPException(status_code=404, detail="sandbox not found")
    reaper.touch(sandbox_id)
    return {"ok": True, "sandbox_id": sandbox_id}


@app.get(
    "/api/sandboxes",
    dependencies=[Depends(require_internal_token)],
)
def list_sandboxes():
    records = manager.list()
    return {
        "sandboxes": [asdict(record) for record in records],
        "count": len(records),
    }


@app.delete(
    "/api/sandboxes/{sandbox_id}",
    dependencies=[Depends(require_internal_token)],
)
def delete_sandbox(sandbox_id: str):
    manager.delete(sandbox_id)
    reaper.forget(sandbox_id)
    return {"ok": True, "sandbox_id": sandbox_id}
