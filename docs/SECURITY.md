# PyFaaS Security

## Threat Model

PyFaaS executes **untrusted user code**. This is the highest-risk aspect of the platform. The threat model assumes:

- Users may intentionally try to escape the sandbox
- Users may try to access other users' data
- Users may try to exfiltrate platform credentials
- Users may try to cause denial of service
- External attackers may try to exploit the API

---

## Defense-in-Depth Layers

### Layer 1: Input Validation (Pydantic)

Every API request is validated with strict Pydantic v2 schemas. Invalid data is rejected before touching the database.

### Layer 2: AST-Based Code Validation

Before storing a function version, PyFaaS parses every `.py` file with Python's `ast` module and rejects:

**Forbidden calls:**
- `eval()`, `exec()`, `compile()`
- `__import__()`
- `open()`, `input()`

**Forbidden imports:**
- `os`, `sys`, `subprocess`, `socket`
- `ctypes`, `cffi`, `importlib`
- `multiprocessing`, `threading`
- `pickle`, `marshal` (deserialization risks)
- And [many more](../shared/security/code_validator.py)

**Forbidden attribute access:**
- `.system()`, `.popen()`, `.fork()`
- `.__dict__`, `.__builtins__`, `.__globals__`

**Important caveat**: AST analysis is a best-effort control. A sufficiently motivated attacker with access to allowed libraries may find bypass paths. The primary sandbox is gVisor.

### Layer 3: gVisor Runtime Isolation

All execution pods run with `runtimeClassName: gvisor`. gVisor's `runsc` intercepts every syscall made by user code and validates it against a safe subset.

This means even if user code bypasses AST validation and calls `os.fork()`, gVisor intercepts the `fork` syscall and may block or isolate it at the kernel interface.

### Layer 4: Kubernetes Security Context

Every execution pod has:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 65534        # nobody
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
```

This means:
- Cannot write to the container filesystem (only writable mounts: `/tmp`, `/work` via emptyDir)
- Cannot gain root
- Cannot gain new capabilities
- Cannot exploit most SUID binaries

### Layer 5: NetworkPolicy Isolation

Execution pods in `sopm-sandbox` can only reach:
- DNS (port 53)
- MinIO (for artifact download)
- Optionally the internet (configurable — remove the internet egress rule to fully isolate)

They cannot reach:
- PostgreSQL
- Redis
- Other pods in `sopm` namespace
- The Kubernetes API

### Layer 6: RBAC

- API pods have no K8s API access (`automountServiceAccountToken: false`)
- Worker pods can only create/get/delete Jobs and read pod logs in `sopm-sandbox`
- Runner (sandbox) pods have no K8s API access

### Layer 7: Tenant Isolation

Every API endpoint that accesses user-owned resources (functions, executions, schedules) filters by `owner_id = current_user.id`. A user cannot access another user's resources even with a valid token.

Errors return 404 (not 403) to prevent enumeration attacks.

---

## Secret Management

All secrets are stored in Kubernetes Secrets and injected as environment variables. No secret is:
- Hardcoded in source code
- Written to logs
- Included in build artifacts
- Committed to version control

For production, use:
- [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) — encrypts secrets before committing
- [External Secrets Operator](https://external-secrets.io/) — syncs from Vault/AWS SSM/GCP Secret Manager
- [Vault Agent Injector](https://developer.hashicorp.com/vault/docs/platform/k8s/injector) — dynamic credentials with lease rotation

---

## Authentication

- Passwords are hashed with bcrypt (work factor: default, ~12)
- JWTs use HS256 with a 256-bit random secret
- Access tokens expire in 60 minutes (configurable)
- Refresh tokens expire in 7 days (configurable)
- No token revocation list — short expiry is the mitigation

To add token revocation (if needed), store a `jti` claim in Redis with TTL matching the token expiry.

---

## Supply Chain

The sandbox runner image (`Dockerfile.runner`) installs only:
- `minio` (artifact download)
- `requests`, `httpx` (HTTP clients)

User code is ZIP-extracted at runtime, not baked into the image. This means:
- No user code in image layers
- No credentials in user images
- Each execution gets a fresh ephemeral filesystem

---

## Security Scanning

The CI pipeline runs:
- **bandit**: Static analysis for Python security issues
- **trivy**: Container image vulnerability scanning (CRITICAL + HIGH)
- **ruff S**: Ruff security rules (subset of bandit)

Trivy results are uploaded as GitHub SARIF for Security tab visibility.

---

## Reporting Vulnerabilities

Email: security@yourorg.com

Please include:
1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if any)

We aim to respond within 48 hours and patch within 7 days for critical issues.
