# Production Deployment Guide — Public Beta v1.0

## 1. Overview
This document specifies the production deployment protocol for the **AI Social Media Content Platform**.

---

## 2. Infrastructure Prerequisites
- **Container Runtime:** Docker 24.0+ & Docker Compose v2.20+
- **Database:** PostgreSQL 16 (AWS Aurora Serverless v2 recommended)
- **Cache:** Redis 7.2 Enterprise Cluster
- **Analytics:** ClickHouse 24.3 Server Cluster
- **Ingress & CDN:** Cloudflare WAF / AWS Application Load Balancer (ALB) with SSL termination (TLS 1.3)

---

## 3. Environment Setup
Copy `.env.production` template and populate sensitive secrets via HashiCorp Vault or AWS Secrets Manager:
```bash
cp .env.production .env
```

---

## 4. Docker Deployment
```bash
# Build production container images
docker compose -f docker-compose.yml build

# Run database migrations
docker compose run --rm backend alembic upgrade head

# Start production stack
docker compose -f docker-compose.yml up -d
```

---

## 5. Verification & Health Probes
```bash
# Verify Liveness Probe
curl -i http://localhost:8000/healthz

# Verify Readiness Probe
curl -i http://localhost:8000/readyz
```

---

## 6. Zero Downtime Rollout Strategy
Use Argo Rollouts or Kubernetes Canary Deployment:
1. Deploy 10% canary traffic to new image release.
2. Monitor 5-minute error rate and P95 latency.
3. Automatically promote canary to 100% upon zero anomaly detection.
