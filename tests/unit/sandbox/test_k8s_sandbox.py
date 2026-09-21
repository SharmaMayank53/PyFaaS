from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from kubernetes.client.exceptions import ApiException

from sandbox import k8s_sandbox
from sandbox.k8s_sandbox import KubernetesSandbox


@pytest.fixture
def sandbox_settings(monkeypatch):
    settings = SimpleNamespace(
        sandbox_enabled=True,
        sandbox_namespace="sopm-sandbox",
        sandbox_runtime_class="gvisor",
        sandbox_service_account="sopm-runner",
        sandbox_image="sopm/runner:latest",
        sandbox_image_pull_policy="IfNotPresent",
        sandbox_default_timeout=300,
        sandbox_cpu_request="100m",
        sandbox_cpu_limit="500m",
        sandbox_memory_request="128Mi",
        sandbox_memory_limit="512Mi",
    )
    monkeypatch.setattr(k8s_sandbox, "settings", settings)
    return settings


def make_sandbox() -> KubernetesSandbox:
    sandbox = object.__new__(KubernetesSandbox)
    sandbox._namespace = "sopm-sandbox"
    sandbox._runtime_class_checked = False
    return sandbox


def test_job_spec_is_gvisor_restricted_and_uses_function_memory(sandbox_settings):
    created = {}
    sandbox = make_sandbox()
    sandbox._batch = SimpleNamespace(
        create_namespaced_job=lambda namespace, body: created.update(namespace=namespace, body=body)
    )

    sandbox._create_job(
        "sopm-exec-test",
        {
            "execution_id": "e" * 36,
            "function_id": "f" * 36,
            "artifact_path": "functions/f/v/source.zip",
            "entrypoint": "handler.handler",
            "payload": {},
            "timeout": 7,
            "memory_mb": 96,
            "environment": {},
        },
    )

    job = created["body"]
    pod_spec = job.spec.template.spec
    container = pod_spec.containers[0]

    assert pod_spec.runtime_class_name == "gvisor"
    assert pod_spec.service_account_name == "sopm-runner"
    assert pod_spec.automount_service_account_token is False
    assert pod_spec.security_context.run_as_non_root is True
    assert pod_spec.security_context.run_as_user == 65534
    assert pod_spec.security_context.run_as_group == 65534
    assert container.security_context.allow_privilege_escalation is False
    assert container.security_context.read_only_root_filesystem is True
    assert container.security_context.capabilities.drop == ["ALL"]
    assert container.resources.limits["memory"] == "96Mi"
    assert container.resources.requests["memory"] == "96Mi"
    assert job.spec.active_deadline_seconds == 7
    assert job.spec.template.metadata.labels["sopm/network-profile"] == "artifact-only"


def test_runtime_class_preflight_fails_closed_when_missing(sandbox_settings):
    sandbox = make_sandbox()

    def missing_runtime_class(name: str):
        assert name == "gvisor"
        raise ApiException(status=404, reason="Not Found")

    sandbox._node = SimpleNamespace(read_runtime_class=missing_runtime_class)

    with pytest.raises(ApiException) as exc_info:
        sandbox._ensure_runtime_class()

    assert exc_info.value.status == 404
    assert "RuntimeClass 'gvisor' is not registered" in exc_info.value.reason


@pytest.mark.asyncio
async def test_failed_job_classifies_deadline_as_timeout(sandbox_settings):
    sandbox = make_sandbox()
    job = SimpleNamespace(
        status=SimpleNamespace(
            conditions=[SimpleNamespace(type="Failed", reason="DeadlineExceeded")]
        )
    )

    result = await sandbox._classify_failed_job("job", job, "looping")

    assert result.success is False
    assert result.timed_out is True
    assert result.error == "Execution timed out"


@pytest.mark.asyncio
async def test_failed_job_classifies_oomkilled_as_memory_limit(sandbox_settings):
    sandbox = make_sandbox()
    terminated = SimpleNamespace(reason="OOMKilled")
    state = SimpleNamespace(terminated=terminated)
    container_status = SimpleNamespace(state=state)
    pod = SimpleNamespace(status=SimpleNamespace(container_statuses=[container_status]))
    sandbox._get_pods_for_job = AsyncMock(return_value=SimpleNamespace(items=[pod]))
    job = SimpleNamespace(status=SimpleNamespace(conditions=[]))

    result = await sandbox._classify_failed_job("job", job, "allocating")

    assert result.success is False
    assert result.timed_out is False
    assert result.error == "Execution exceeded memory limit"
