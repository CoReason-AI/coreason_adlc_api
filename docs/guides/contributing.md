# Contributing Guide

Thank you for your interest in contributing to the Coreason ADLC API! This document outlines the standards and workflows for development.

## Development Protocol

We follow a strict **Iterative, Atomic, Test-Driven** development protocol.

1.  **Atomic Units**: Break down tasks into small, independently testable units.
2.  **Test First**: Write tests for your unit *before* or *alongside* implementation.
3.  **No Regressions**: Ensure all existing tests pass before committing.
4.  **100% Coverage**: We enforce strict 100% test coverage.

## Environment Setup

The project uses **Poetry** for dependency management.

```bash
# Install dependencies
poetry install

# Install pre-commit hooks
poetry run pre-commit install
```

## Code Style

We use **Ruff** for linting and formatting, and **Mypy** for static typing.

*   **Format Code**: `poetry run ruff format .`
*   **Lint Code**: `poetry run ruff check --fix .`
*   **Type Check**: `poetry run mypy .`

## Testing

Run the test suite using `pytest`:

```bash
poetry run pytest
```

Tests are located in the `tests/` directory.

*   `tests/test_*.py`: Unit tests.
*   `tests/complex/`: Integration and complex scenario tests.

## Documentation

Documentation is built with **MkDocs Material**.

*   Edit files in `docs/`.
*   Update `mkdocs.yml` if adding new pages.
*   Build docs: `poetry run mkdocs build --strict`
