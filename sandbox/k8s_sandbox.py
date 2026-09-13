"""
SOPM - Kubernetes Sandbox

Creates and monitors Kubernetes Jobs to execute user functions in
gVisor-isolated containers with strict security policies.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from shared.config import get_settings
from shared.observability.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


@dataclass
class SandboxResult:
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    logs: list[dict[str, str]] = field(default_factory=list)
    duration_ms: int | None = None
    timed_out: bool = False
    k8s_job_name: str | None = None


class KubernetesSandbox:
    """
    Executes user functions as Kubernetes Jobs.

    Each execution gets a fresh, isolated Job with:
    - gVisor RuntimeClass
    - Non-root, read-only filesystem
    - All capabilities dropped
    - NetworkPolicy restricting egress (applied separately)
    """

    def __init__(self) -> None:
        if settings.sandbox_enabled:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                # Fall back to kubeconfig for local dev
                config.load_kube_config()

        self._batch = client.BatchV1Api()
        self._core = client.CoreV1Api()
        self._node = client.NodeV1Api()
        self._namespace = settings.sandbox_namespace
        self._runtime_class_checked = False

    async def execute(self, job_spec: dict[str, Any]) -> SandboxResult:
        """Create a Kubernetes Job, poll until completion, return result."""
        if not settings.sandbox_enabled:
            return await self._local_execute(job_spec)

        execution_id = job_spec["execution_id"]
        job_name = f"sopm-exec-{execution_id[:8]}-{uuid.uuid4().hex[:6]}"
        timeout = job_spec.get("timeout", settings.sandbox_default_timeout)

        start_ms = int(time.monotonic() * 1000)

        try:
            await asyncio.get_event_loop().run_in_executor(None, self._ensure_runtime_class)
            await asyncio.get_event_loop().run_in_executor(
                None, self._create_job, job_name, job_spec
            )
            logger.info(
                "k8s_job_created", job_name=job_name, execution_id=execution_id
            )

            result = await self._wait_for_job(job_name, timeout)
            result.k8s_job_name = job_name
            result.duration_ms = int(time.monotonic() * 1000) - start_ms
            return result

        except ApiException as exc:
            logger.error(
                "k8s_api_error",
                job_name=job_name,
                status=exc.status,
                reason=exc.reason,
            )
            return SandboxResult(
                success=False,
                error=f"Kubernetes API error: {exc.reason}",
                duration_ms=int(time.monotonic() * 1000) - start_ms,
                k8s_job_name=job_name,
            )
        finally:
            # Best-effort cleanup
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._delete_job, job_name
                )
            except Exception:
                pass

    def _ensure_runtime_class(self) -> None:
        """Fail closed if the configured gVisor RuntimeClass is not registered."""
        if self._runtime_class_checked:
            return
        runtime_class = settings.sandbox_runtime_class
        if not runtime_class:
            raise ApiException(status=400, reason="SANDBOX_RUNTIME_CLASS is required")
        try:
            self._node.read_runtime_class(runtime_class)
        except ApiException as exc:
            if exc.status == 404:
                raise ApiException(
                    status=404,
                    reason=f"RuntimeClass '{runtime_class}' is not registered; install gVisor/runsc first",
                ) from exc
            raise
        self._runtime_class_checked = True

    def _memory_limit(self, job_spec: dict[str, Any]) -> str:
        memory_mb = int(job_spec.get("memory_mb") or 0)
        if memory_mb <= 0:
            return settings.sandbox_memory_limit
        return f"{memory_mb}Mi"

    def _memory_request(self, memory_limit: str) -> str:
        try:
            limit_mib = int(memory_limit.removesuffix("Mi"))
        except ValueError:
            return settings.sandbox_memory_request
        request_mib = min(limit_mib, 128)
        return f"{request_mib}Mi"

    def _create_job(self, job_name: str, job_spec: dict[str, Any]) -> None:
        """Synchronous; runs in executor thread."""
        import json

        env_vars = [
            client.V1EnvVar(name="SOPM_EXECUTION_ID", value=job_spec["execution_id"]),
            client.V1EnvVar(name="SOPM_ARTIFACT_PATH", value=job_spec.get("artifact_path", "")),
            client.V1EnvVar(name="SOPM_ENTRYPOINT", value=job_spec["entrypoint"]),
            client.V1EnvVar(name="SOPM_PAYLOAD", value=json.dumps(job_spec.get("payload", {}))),
            client.V1EnvVar(name="SOPM_TIMEOUT", value=str(job_spec.get("timeout", 300))),
            client.V1EnvVar(name="HOME", value="/tmp"),
            client.V1EnvVar(name="PIP_CACHE_DIR", value="/tmp/pip-cache"),
            client.V1EnvVar(name="PYTHONPYCACHEPREFIX", value="/tmp/pycache"),
            # MinIO config for artifact download
            client.V1EnvVar(
                name="MINIO_ENDPOINT",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name="sopm-secrets", key="minio-endpoint"
                    )
                ),
            ),
            client.V1EnvVar(
                name="MINIO_ACCESS_KEY",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name="sopm-secrets", key="minio-access-key"
                    )
                ),
            ),
            client.V1EnvVar(
                name="MINIO_SECRET_KEY",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name="sopm-secrets", key="minio-secret-key"
                    )
                ),
            ),
        ]

        if job_spec.get("source_code") is not None:
            env_vars.append(client.V1EnvVar(name="SOPM_SOURCE_CODE", value=job_spec["source_code"]))

        # Inject user-defined environment variables
        for k, v in (job_spec.get("environment") or {}).items():
            env_vars.append(client.V1EnvVar(name=k, value=str(v)))

        security_context = client.V1SecurityContext(
            run_as_non_root=True,
            run_as_user=65534,  # nobody
            run_as_group=65534,
            privileged=False,
            read_only_root_filesystem=True,
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        )

        pod_security_context = client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=65534,
            run_as_group=65534,
            fs_group=65534,
            fs_group_change_policy="OnRootMismatch",
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        )

        memory_limit = self._memory_limit(job_spec)
        resources = client.V1ResourceRequirements(
            requests={
                "cpu": settings.sandbox_cpu_request,
                "memory": self._memory_request(memory_limit),
            },
            limits={
                "cpu": settings.sandbox_cpu_limit,
                "memory": memory_limit,
            },
        )

        container = client.V1Container(
            name="runner",
            image=settings.sandbox_image,
            image_pull_policy=settings.sandbox_image_pull_policy,
            env=env_vars,
            resources=resources,
            security_context=security_context,
            volume_mounts=[
                client.V1VolumeMount(name="tmp", mount_path="/tmp"),
                client.V1VolumeMount(name="work", mount_path="/work"),
            ],
        )

        pod_spec = client.V1PodSpec(
            runtime_class_name=settings.sandbox_runtime_class,
            service_account_name=settings.sandbox_service_account,
            restart_policy="Never",
            containers=[container],
            security_context=pod_security_context,
            automount_service_account_token=False,
            volumes=[
                client.V1Volume(
                    name="tmp",
                    empty_dir=client.V1EmptyDirVolumeSource(size_limit="100Mi"),
                ),
                client.V1Volume(
                    name="work",
                    empty_dir=client.V1EmptyDirVolumeSource(size_limit="500Mi"),
                ),
            ],
        )

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/component": "sandbox",
                    "sopm/network-profile": "artifact-only",
                    "sopm/execution-id": job_spec["execution_id"][:63],
                    "sopm/function-id": job_spec["function_id"][:63],
                },
                annotations={
                    "sopm/execution-id": job_spec["execution_id"],
                    "sopm/function-id": job_spec["function_id"],
                },
            ),
            spec=client.V1JobSpec(
                backoff_limit=0,
                active_deadline_seconds=job_spec.get("timeout", settings.sandbox_default_timeout),
                ttl_seconds_after_finished=300,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app.kubernetes.io/component": "sandbox",
                            "sopm/network-profile": "artifact-only",
                            "sopm/execution-id": job_spec["execution_id"][:63],
                        }
                    ),
                    spec=pod_spec,
                ),
            ),
        )

        self._batch.create_namespaced_job(namespace=self._namespace, body=job)

    async def _wait_for_job(self, job_name: str, timeout: int) -> SandboxResult:
        """Poll the Job status until it reaches a terminal state."""
        deadline = time.monotonic() + timeout + 10
        poll_interval = 0.25

        while time.monotonic() < deadline:
            job = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._batch.read_namespaced_job(
                    name=job_name, namespace=self._namespace
                ),
            )

            if job.status.succeeded:
                logs = await self._get_pod_logs(job_name)
                result = self._parse_result_from_logs(logs)
                return SandboxResult(
                    success=True,
                    result=result,
                    logs=self._format_logs(logs),
                )

            if job.status.failed:
                logs = await self._get_pod_logs(job_name)
                return await self._classify_failed_job(job_name, job, logs)

            await asyncio.sleep(poll_interval)

        return SandboxResult(
            success=False,
            timed_out=True,
            error="Worker-side timeout waiting for Kubernetes Job",
        )

    async def _get_pods_for_job(self, job_name: str):
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._core.list_namespaced_pod(
                namespace=self._namespace,
                label_selector=f"job-name={job_name}",
            ),
        )

    async def _classify_failed_job(self, job_name: str, job: Any, logs: str) -> SandboxResult:
        timed_out = any(
            condition.type == "Failed" and condition.reason == "DeadlineExceeded"
            for condition in (job.status.conditions or [])
        )
        if timed_out:
            return SandboxResult(
                success=False,
                timed_out=True,
                error="Execution timed out",
                logs=self._format_logs(logs),
            )

        try:
            pods = await self._get_pods_for_job(job_name)
            for pod in pods.items:
                for status in (pod.status.container_statuses or []):
                    terminated = status.state.terminated if status.state else None
                    if terminated and terminated.reason == "OOMKilled":
                        return SandboxResult(
                            success=False,
                            error="Execution exceeded memory limit",
                            logs=self._format_logs(logs),
                        )
                    if terminated and terminated.reason:
                        return SandboxResult(
                            success=False,
                            error=f"Execution failed: {terminated.reason}",
                            logs=self._format_logs(logs),
                        )
        except Exception as exc:
            logger.warning("pod_failure_classification_failed", job=job_name, error=str(exc))

        return SandboxResult(
            success=False,
            error="Execution failed",
            logs=self._format_logs(logs),
        )

    async def _get_pod_logs(self, job_name: str) -> str:
        """Fetch logs from the pod associated with this Job."""
        try:
            pods = await self._get_pods_for_job(job_name)
            if not pods.items:
                return ""
            pod_name = pods.items[0].metadata.name
            logs = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._core.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=self._namespace,
                    tail_lines=1000,
                ),
            )
            return logs or ""
        except Exception as exc:
            logger.warning("pod_log_fetch_failed", job=job_name, error=str(exc))
            return ""

    def _parse_result_from_logs(self, logs: str) -> dict[str, Any] | None:
        """
        The runner writes a JSON result line prefixed with SOPM_RESULT:.
        Extract and parse it.
        """
        import json

        for line in reversed(logs.splitlines()):
            if line.startswith("SOPM_RESULT:"):
                try:
                    return json.loads(line[len("SOPM_RESULT:"):])
                except json.JSONDecodeError:
                    pass
        return None

    def _format_logs(self, raw: str) -> list[dict[str, str]]:
        entries = []
        for line in raw.splitlines():
            if line.startswith("SOPM_RESULT:"):
                continue
            entries.append({"level": "INFO", "stream": "stdout", "message": line})
        return entries

    def _delete_job(self, job_name: str) -> None:
        self._batch.delete_namespaced_job(
            name=job_name,
            namespace=self._namespace,
            body=client.V1DeleteOptions(propagation_policy="Foreground"),
        )

    async def _local_execute(self, job_spec: dict[str, Any]) -> SandboxResult:
        """
        Local execution mode (sandbox_enabled=false).
        Used for integration testing only â€” NOT for production.
        """
        logger.warning(
            "local_execution_mode",
            execution_id=job_spec["execution_id"],
            message="SANDBOX DISABLED â€” running code locally. Production use requires sandbox.",
        )
        return SandboxResult(
            success=True,
            result={"message": "local execution (sandbox disabled)"},
            logs=[{"level": "WARN", "stream": "stdout", "message": "sandbox disabled"}],
            duration_ms=0,
        )


async def _docker_local_execute(self: KubernetesSandbox, job_spec: dict[str, Any]) -> SandboxResult:
    """
    Docker development execution path for SANDBOX_ENABLED=false.

    This runs the normal sandbox runner in a subprocess inside the worker
    container. It is useful locally, but it is not a security boundary.
    """
    import json
    import os
    import sys

    timeout = job_spec.get("timeout", settings.sandbox_default_timeout)
    start_ms = int(time.monotonic() * 1000)

    logger.warning(
        "local_execution_mode",
        execution_id=job_spec["execution_id"],
        message="SANDBOX DISABLED - running code in the worker container.",
    )

    env = os.environ.copy()
    env.update(
        {
            "SOPM_EXECUTION_ID": job_spec["execution_id"],
            "SOPM_ARTIFACT_PATH": job_spec.get("artifact_path", ""),
                "SOPM_ENTRYPOINT": job_spec.get("entrypoint", "handler.handler"),
                "SOPM_PAYLOAD": json.dumps(job_spec.get("payload", {})),
                "SOPM_TIMEOUT": str(timeout),
                "SOPM_WORK_DIR": f"/tmp/sopm-exec-{job_spec['execution_id']}",
                "SOPM_VERSION_ID": str(job_spec.get("version_id", "unknown")),
                "SOPM_CACHE_DIR": f"/tmp/sopm-cache-{job_spec.get('version_id', 'unknown')}",
                "HOME": "/tmp",
                "PIP_CACHE_DIR": "/tmp/pip-cache",
                "PYTHONPYCACHEPREFIX": "/tmp/pycache",
            }
        )
    if job_spec.get("source_code") is not None:
        env["SOPM_SOURCE_CODE"] = str(job_spec["source_code"])
        env.pop("SOPM_CACHE_DIR", None)

    for key, value in (job_spec.get("environment") or {}).items():
        env[str(key)] = str(value)

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "sandbox.runner",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
    except asyncio.TimeoutError:
        proc.kill()
        stdout, _ = await proc.communicate()
        raw_logs = stdout.decode(errors="replace")
        return SandboxResult(
            success=False,
            timed_out=True,
            error="Execution timed out",
            logs=self._format_logs(raw_logs),
            duration_ms=int(time.monotonic() * 1000) - start_ms,
        )

    raw_logs = stdout.decode(errors="replace")
    parsed_result = self._parse_result_from_logs(raw_logs)
    success = proc.returncode == 0

    error = None
    if not success:
        if isinstance(parsed_result, dict):
            error = parsed_result.get("error") or "Execution failed"
        else:
            error = "Execution failed"

    return SandboxResult(
        success=success,
        result=parsed_result,
        error=error,
        logs=self._format_logs(raw_logs),
        duration_ms=int(time.monotonic() * 1000) - start_ms,
    )


KubernetesSandbox._local_execute = _docker_local_execute


