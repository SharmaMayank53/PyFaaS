# PyFaaS Deployment Guide

This guide covers deploying PyFaaS to a production Kubernetes cluster from scratch.

---

## Prerequisites

| Tool | Version |
|---|---|
| Kubernetes | 1.28+ |
| kubectl | matching cluster version |
| Helm | 3.x (for infra dependencies) |
| gVisor (runsc) | installed on all nodes |
| Docker | 24+ |

---

## Phase 1: Infrastructure Dependencies

### Install gVisor on nodes

Follow the [official gVisor installation guide](https://gvisor.dev/docs/user_guide/install/) for your distribution, then install the containerd shim:

```bash
# On each node
runsc install
systemctl restart containerd
```

### Create RuntimeClass

```bash
kubectl apply -f - <<EOF
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
EOF
```

### Deploy PostgreSQL

Use the Bitnami Helm chart or your managed database service:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami

helm install sopm-postgres bitnami/postgresql \
  --namespace sopm \
  --create-namespace \
  --set auth.username=sopm \
  --set auth.password=STRONG_PASSWORD \
  --set auth.database=sopm \
  --set primary.persistence.size=20Gi
```

### Deploy Redis

```bash
helm install sopm-redis bitnami/redis \
  --namespace sopm \
  --set auth.password=STRONG_REDIS_PASSWORD \
  --set architecture=standalone \
  --set master.persistence.size=5Gi
```

### Deploy MinIO

```bash
helm repo add minio https://charts.min.io/

helm install sopm-minio minio/minio \
  --namespace sopm \
  --set rootUser=sopm_access \
  --set rootPassword=STRONG_MINIO_SECRET \
  --set persistence.size=50Gi \
  --set resources.requests.memory=512Mi
```

---

## Phase 2: Platform Secrets

Generate secrets:

```bash
# Generate a strong SECRET_KEY
openssl rand -hex 32

# Collect all values and create the secret
kubectl create secret generic sopm-secrets \
  --namespace sopm \
  --from-literal=secret-key="$(openssl rand -hex 32)" \
  --from-literal=database-url="postgresql+asyncpg://sopm:STRONG_PASSWORD@sopm-postgres:5432/sopm" \
  --from-literal=database-url-sync="postgresql+psycopg2://sopm:STRONG_PASSWORD@sopm-postgres:5432/sopm" \
  --from-literal=redis-url="redis://:STRONG_REDIS_PASSWORD@sopm-redis-master:6379/0" \
  --from-literal=minio-endpoint="sopm-minio:9000" \
  --from-literal=minio-access-key="sopm_access" \
  --from-literal=minio-secret-key="STRONG_MINIO_SECRET"

# Mirror MinIO secrets into sandbox namespace
kubectl create secret generic sopm-secrets \
  --namespace sopm-sandbox \
  --from-literal=minio-endpoint="sopm-minio.sopm.svc.cluster.local:9000" \
  --from-literal=minio-access-key="sopm_access" \
  --from-literal=minio-secret-key="STRONG_MINIO_SECRET"
```

For production, use [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) or [External Secrets Operator](https://external-secrets.io/) instead of plain Kubernetes Secrets.

---

## Phase 3: Build and Push Images

```bash
# Set your registry
REGISTRY=ghcr.io/yourorg
TAG=$(git rev-parse --short HEAD)

docker build -f deploy/docker/Dockerfile.api -t $REGISTRY/sopm-api:$TAG .
docker build -f deploy/docker/Dockerfile.worker -t $REGISTRY/sopm-worker:$TAG .
docker build -f deploy/docker/Dockerfile.runner -t $REGISTRY/sopm-runner:$TAG .

docker push $REGISTRY/sopm-api:$TAG
docker push $REGISTRY/sopm-worker:$TAG
docker push $REGISTRY/sopm-runner:$TAG
```

---

## Phase 4: Apply Kubernetes Manifests

```bash
# Namespaces and RBAC
kubectl apply -f k8s/base/namespace-rbac.yaml

# Network policies
kubectl apply -f k8s/base/network-policies.yaml

# Run database migrations (Job)
kubectl create job sopm-migrate \
  --namespace sopm \
  --image=$REGISTRY/sopm-api:$TAG \
  -- alembic upgrade head
kubectl wait --for=condition=complete job/sopm-migrate -n sopm --timeout=120s

# Deploy platform
kubectl apply -f k8s/base/deployments.yaml

# Wait for rollout
kubectl rollout status deployment/sopm-api -n sopm --timeout=120s
kubectl rollout status deployment/sopm-worker -n sopm --timeout=120s
```

---

## Phase 5: Ingress

Example with NGINX Ingress Controller:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sopm-api
  namespace: sopm
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"  # For function uploads
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - sopm.yourdomain.com
      secretName: sopm-tls
  rules:
    - host: sopm.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: sopm-api
                port:
                  number: 80
```

---

## Phase 6: Monitoring

```bash
# Add Prometheus
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace

# Apply PyFaaS service monitor
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: sopm-api
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: api
  namespaceSelector:
    matchNames: [sopm]
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
EOF
```

---

## Upgrades

### Rolling upgrade (no downtime)

```bash
TAG=new_image_tag

kubectl set image deployment/sopm-api api=$REGISTRY/sopm-api:$TAG -n sopm
kubectl set image deployment/sopm-worker worker=$REGISTRY/sopm-worker:$TAG -n sopm

kubectl rollout status deployment/sopm-api -n sopm
kubectl rollout status deployment/sopm-worker -n sopm
```

### Run migrations before upgrading API

Always run `alembic upgrade head` before deploying a new API version when there are schema changes. Alembic migrations are designed to be forward-compatible.

---

## Backup

### PostgreSQL

```bash
# Backup
kubectl exec -n sopm deployment/sopm-postgres -- \
  pg_dump -U sopm sopm | gzip > sopm-$(date +%Y%m%d).sql.gz

# Restore
gunzip -c sopm-20240101.sql.gz | kubectl exec -i -n sopm \
  deployment/sopm-postgres -- psql -U sopm sopm
```

### MinIO

Use `mc mirror` or MinIO's built-in replication to back up artifacts.

---

## Operational Runbook

### Worker is not processing jobs

1. Check queue depth: `GET /metrics` → look at `sopm_queue_depth`
2. Check worker logs: `kubectl logs -n sopm -l app.kubernetes.io/component=worker`
3. Check worker heartbeats: `redis-cli keys 'sopm:worker:*:heartbeat'`
4. Verify K8s sandbox namespace exists and worker RBAC is correct

### Execution stuck in RUNNING

1. Check the K8s Job: `kubectl get jobs -n sopm-sandbox | grep <execution_id_prefix>`
2. Check pod logs: `kubectl logs -n sopm-sandbox <pod_name>`
3. Manually force-complete via DB if job has finished but result wasn't written:
   ```sql
   UPDATE executions SET status='FAILED', error_message='manual override'
   WHERE id='...' AND status='RUNNING';
   ```

### DLQ jobs

Jobs in the DLQ can be inspected via Redis:
```bash
redis-cli ZRANGE sopm:dlq 0 -1 WITHSCORES
```

Requeue a job:
```bash
# Move from DLQ back to main queue
redis-cli ZPOPMIN sopm:dlq
redis-cli ZADD sopm:queue <score> <job_json>
```
