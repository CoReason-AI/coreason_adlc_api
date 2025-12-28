# Deployment & Operations Guide

This guide covers how to deploy the `coreason-adlc-api` in a production environment.

The package is designed to be installed via `pip` and run as a standalone service, or deployed as a Docker container.

## 1. Installation

The package is available on PyPI.

```bash
pip install coreason-adlc-api
```

### Verification
Once installed, you can verify the installation by checking the version:

```bash
coreason-api --help
```

## 2. Configuration (Environment Variables)

The application is configured entirely via environment variables. Create a `.env` file or export these variables in your shell/container environment.

### Core Settings

| Variable | Description | Default | Required in Prod |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | Environment name (e.g., `production`, `staging`). | `development` | Yes |
| `DEBUG` | Enable debug logs and stack traces. | `False` | No (Keep False) |
| `PORT` | The port the server listens on. | `8000` | No |
| `HOST` | The interface to bind to. | `0.0.0.0` | No |

### Database (PostgreSQL)

The API requires a PostgreSQL 14+ database.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `POSTGRES_USER` | Database username. | `postgres` |
| `POSTGRES_PASSWORD` | Database password. | `postgres` |
| `POSTGRES_HOST` | Hostname or IP of the DB server. | `localhost` |
| `POSTGRES_PORT` | Port number. | `5432` |
| `POSTGRES_DB` | Database name. | `coreason_db` |

### Cache & Queue (Redis)

Redis is used for the Budget Gatekeeper and Telemetry Queue.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `REDIS_HOST` | Hostname or IP of Redis. | `localhost` |
| `REDIS_PORT` | Redis port. | `6379` |
| `REDIS_DB` | Redis database index. | `0` |
| `REDIS_PASSWORD` | Optional password for AUTH. | `None` |

### Security & Vault

Critical security parameters.

| Variable | Description | Requirement |
| :--- | :--- | :--- |
| `ENCRYPTION_KEY` | **CRITICAL:** 32-byte hex string used for AES-256 encryption of Vault secrets. | **Must be overridden.** Do not use the default in production. |
| `JWT_SECRET` | Secret key for signing/verifying JWTs. | **Must be overridden.** |
| `JWT_ALGORITHM` | Algorithm for JWT (e.g., `HS256`, `RS256`). | `HS256` |

### Governance

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DAILY_BUDGET_LIMIT`| The hard cap (in USD) for daily user spend. | `50.0` |
| `ENTERPRISE_LICENSE_KEY` | License key to unlock Enterprise features (SSO, Oracle drivers). | `None` |

## 3. Database Initialization

The package does not automatically migrate the database on startup to avoid race conditions in scaled deployments. You must run the DDL scripts manually or via a migration tool.

The DDL is provided in the `ddl.sql` files within the package or in the documentation appendix.

**Key Schemas to create:**
1. `identity`
2. `workbench`
3. `telemetry`
4. `vault`

*Refer to the [Architecture](../architecture.md) or Requirements document for the full Schema definitions.*

## 4. Running the Service

### Bare Metal / VM

After setting environment variables:

```bash
coreason-api start
```

This will launch the Uvicorn server on the configured `HOST` and `PORT`.

### Docker

If you prefer containers, you can build a lightweight image:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install the package
RUN pip install coreason-adlc-api

# Create a user for security
RUN useradd -m coreason
USER coreason

# Expose port
EXPOSE 8000

# Entrypoint
CMD ["coreason-api", "start"]
```

Build and run:

```bash
docker build -t coreason-api .
docker run -p 8000:8000 --env-file .env coreason-api
```

## 5. Operations

### Monitoring

- **Health Check**: `GET /health` (Standard 200 OK)
- **Metrics**: The application logs telemetry to the `telemetry_logs` table. Monitor the `latency_ms` and `cost_usd` columns.

### Key Rotation

To rotate the `ENCRYPTION_KEY`:
1. This feature is currently **manual**.
2. You must decrypt all secrets with the old key and re-encrypt with the new key in the `vault.secrets` table.
3. *Note: Automated key rotation is planned for v2.0.*
