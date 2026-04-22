# CI Engine Example Pipelines

This directory contains example pipeline configurations for CI Engine.

## Quick Start

```bash
# Create a build from a pipeline file
curl -X POST http://localhost:8000/api/builds \
  -H "Content-Type: application/json" \
  -d @examples/simple-pipeline.yaml
```

## Examples

### 1. Simple Pipeline (`simple-pipeline.yaml`)

Minimal pipeline with build and test steps:

```yaml
steps:
  - label: "Build"
    command: "make build"
  - label: "Test"
    command: "make test"
```

### 2. Multi-Stage Pipeline (`multi-stage.yaml`)

Pipeline with build, test, and deploy stages:

```yaml
name: multi-stage-pipeline

env:
  - NODE_ENV=production

steps:
  - label: "Install Dependencies"
    command: "npm ci"
    plugins:
      - npm-cache#v1.0:
          cache_key: "{{ .Env.NODE_ENV }}-{{ checksum package-lock.json }}"
  
  - label: "Lint"
    command: "npm run lint"
  
  - label: "Unit Tests"
    command: "npm test -- --coverage"
  
  - label: "Build"
    command: "npm run build"
    artifact_paths:
      - dist/**
  
  - label: "Deploy to Staging"
    command: "npm run deploy:staging"
    if: build.branch == "main"
  
  - label: "Deploy to Production"
    command: "npm run deploy:prod"
    if: build.branch == "main" && build.job.status == "passed"
```

### 3. Matrix Strategy (`matrix.yaml`)

Run jobs in parallel across multiple configurations:

```yaml
name: matrix-pipeline

steps:
  - label: "Test {{matrix.node}} on {{matrix.os}}"
    command: "npm test"
    matrix:
      node: ["16", "18", "20"]
      os: ["ubuntu-latest", "macos-latest"]
    env:
      NODE_VERSION: "{{matrix.node}}"
  
  - label: "Build for {{matrix.platform}}"
    command: "make build-{{matrix.platform}}"
    matrix:
      platform: ["linux", "darwin", "windows"]
```

### 4. Dependencies (`dependencies.yaml`)

Pipeline with job dependencies:

```yaml
name: dependency-pipeline

steps:
  - label: "Setup"
    command: "make setup"
    id: setup
  
  - label: "Backend Tests"
    command: "make test-backend"
    depends_on: setup
  
  - label: "Frontend Tests"
    command: "make test-frontend"
    depends_on: setup
  
  - label: "Integration Tests"
    command: "make test-integration"
    depends_on:
      - backend-tests
      - frontend-tests
```

### 5. Docker Build (`docker.yaml`)

Build and push Docker images:

```yaml
name: docker-pipeline

steps:
  - label: "Build Docker Image"
    command: |
      docker build -t myapp:$BUILDKITE_COMMIT .
      docker tag myapp:$BUILDKITE_COMMIT myapp:latest
    plugins:
      - docker-compose#v3.7:
          run: app
  
  - label: "Push to Registry"
    command: |
      echo $DOCKER_PASSWORD | docker login -u $DOCKER_USERNAME --password-stdin
      docker push myapp:$BUILDKITE_COMMIT
      docker push myapp:latest
    if: build.branch == "main"
```

### 6. Secret Usage (`secrets.yaml`)

Using secrets in pipeline:

```yaml
name: secrets-pipeline

steps:
  - label: "Deploy with Token"
    command: |
      curl -X POST https://api.example.com/deploy \
        -H "Authorization: Bearer $DEPLOY_TOKEN" \
        -d '{"version": "{{.BUILDKITE_COMMIT}}"}'
    env:
      DEPLOY_TOKEN:
        from_secret: deploy_token
```

### 7. Retry and Timeout (`advanced.yaml`)

Using retry, timeout, and conditional execution:

```yaml
name: advanced-pipeline

steps:
  - label: "Flaky Test"
    command: "make test-flaky"
    retry:
      automatic:
        - exit_status: 1
          limit: 3
    timeout_in_minutes: 10
  
  - label: "Manual Approval"
    command: "echo 'Waiting for approval'"
    branches: "main"
  
  - label: "Deploy"
    command: "make deploy"
    if: build.branch == "main" && build.job("manual-approval").state == "passed"
```

## Pipeline Reference

### Step Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `label` | string | Step name displayed in UI |
| `command` | string | Shell command to execute |
| `depends_on` | string/string[] | Job dependencies |
| `env` | object | Environment variables |
| `plugins` | object[] | Plugins to use |
| `artifact_paths` | string[] | Paths to upload as artifacts |
| `timeout_in_minutes` | int | Job timeout |
| `retry` | object | Retry configuration |
| `if` | string | Conditional execution |
| `skip` | bool/string | Skip this step |
| `parallelism` | int | Number of parallel jobs |
| `matrix` | object | Matrix configuration |

### Environment Variables

Built-in variables:
- `BUILDKITE_COMMIT` - Git commit SHA
- `BUILDKITE_BRANCH` - Git branch name
- `BUILDKITE_BUILD_NUMBER` - Build number
- `BUILDKITE_JOB_ID` - Current job ID
- `BUILDKITE_MESSAGE` - Commit message