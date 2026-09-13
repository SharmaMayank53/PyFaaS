# SOPM Kubernetes/gVisor Isolation

Phase 2 is the production-style sandbox path. Docker Compose keeps `SANDBOX_ENABLED=false` for fast local development only; that mode runs user code inside the worker container and is not a security boundary.

## Required cluster state

A Kubernetes cluster must have gVisor/runsc installed on every node that can run sandbox pods. SOPM expects this RuntimeClass:

```powershell
kubectl apply -f k8s/base/runtimeclass-gvisor.yaml
kubectl get runtimeclass gvisor
```

Before calling this path validated, inspect a real execution pod:

```powershell
kubectl -n sopm-sandbox get pods -l app.kubernetes.io/component=sandbox
kubectl -n sopm-sandbox describe pod <pod-name>
```

The pod must show `Runtime Class Name: gvisor`. If the RuntimeClass is missing, the worker now fails closed before creating execution jobs.

## Sandbox guarantees configured here

Each execution is a fresh Kubernetes Job in `sopm-sandbox` with:

- `runtimeClassName: gvisor`
- non-root UID/GID `65534`
- `allowPrivilegeEscalation: false`
- all Linux capabilities dropped
- `readOnlyRootFilesystem: true`
- writable `emptyDir` mounts only at `/tmp` and `/work`
- `automountServiceAccountToken: false`
- no Role/RoleBinding for the runner service account
- default-deny NetworkPolicy in `sopm-sandbox`
- egress allowed only to DNS and MinIO artifact storage
- memory limit set from the function version `memory_mb`
- Kubernetes Job deadline set from the function timeout

The runner removes MinIO credentials from its environment before dependency install, import, or handler execution.

## Validation checklist

Run these after deploying to a cluster with gVisor:

```powershell
kubectl apply -f k8s/base/namespace-rbac.yaml
kubectl apply -f k8s/base/runtimeclass-gvisor.yaml
kubectl apply -f k8s/base/network-policies.yaml
kubectl apply -f k8s/base/deployments.yaml
```

Then execute test functions that prove enforcement:

- happy path: returns normally and pod uses RuntimeClass `gvisor`
- timeout: infinite loop with a short function timeout becomes `TIMED_OUT`
- memory: allocation above `memory_mb` reports `Execution exceeded memory limit`
- Kubernetes API: reading the in-cluster service account token or API should fail
- network: outbound internet/internal cluster calls should fail except DNS and MinIO artifact fetch
- filesystem: writing outside `/tmp` or `/work` should fail because the root filesystem is read-only
- concurrency: two simultaneous executions should not see each other's `/tmp` or `/work` state

This repository includes unit tests for the generated Job spec and failure classification. The final RuntimeClass proof still requires a real cluster because Docker Compose cannot emulate gVisor scheduling.