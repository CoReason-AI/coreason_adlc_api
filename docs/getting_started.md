# Getting Started

This guide will help you set up and run the Coreason ADLC API.

## Prerequisites

*   **Python**: 3.12, 3.13, or 3.14 (Note: `presidio-analyzer` compatibility issues may constrain this to <3.14).
*   **Poetry**: Dependency management.
*   **Docker** (Optional): For containerized deployment.
*   **PostgreSQL**: Database for persistent storage.
*   **Redis**: Key-value store for caching and queues.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/CoReason-AI/coreason_adlc_api.git
    cd coreason_adlc_api
    ```

2.  **Install dependencies using Poetry:**
    ```bash
    poetry install
    ```
    This will install all required packages, including development dependencies.

3.  **Download Spacy Model:**
    The PII scrubber requires the `en_core_web_lg` model.
    ```bash
    poetry run python -m spacy download en_core_web_lg
    ```

## Configuration

The application is configured via environment variables. Create a `.env` file or export them directly.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `APP_ENV` | Environment (`development`, `testing`, `production`) | `development` |
| `DEBUG` | Enable debug mode | `False` |
| `SECRET_KEY` | Secret for cryptographic signing | *Required* |
| `DATABASE_URL` | PostgreSQL connection string | *Required* |
| `REDIS_URL` | Redis connection string | *Required* |
| `JWT_SECRET` | Secret for JWT signing | *Required* |
| `JWT_ALGORITHM` | Algorithm for JWT signing (e.g., HS256) | `HS256` |

## Running the Application

### Development Mode

To run the API locally with hot-reloading:

```bash
poetry run uvicorn coreason_adlc_api.app:app --reload
```

The API will be available at `http://127.0.0.1:8000`.
Interactive documentation (Swagger UI) is available at `http://127.0.0.1:8000/docs`.

### Production Mode

Use the provided CLI entry point:

```bash
poetry run coreason-api start
```

Or using Docker:

```bash
docker build -t coreason-api .
docker run -p 8000:8000 --env-file .env coreason-api
```
