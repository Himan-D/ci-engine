# Kubernetes Resources Documentation

This directory contains Kubernetes deployment configurations for CI Engine.

## Resources

### HPA (Horizontal Pod Autoscaler)

The HPA automatically scales the server deployment based on CPU/memory utilization.

**Configuration (values.yaml):**
```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

**Example HPA manifest:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ci-engine-server-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ci-engine-server
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### ServiceMonitor (Prometheus Operator)

For Prometheus Operator-based monitoring, add a ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ci-engine-server
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: ci-engine
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

### PodDisruptionBudget

For zero-downtime deployments:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: ci-engine-server-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/component: server
```

### NetworkPolicy

Restrict traffic to the server:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ci-engine-server-network-policy
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: server
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: production
    ports:
    - protocol: TCP
      port: 8000
```