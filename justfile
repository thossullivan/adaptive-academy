# Full-Stack Project Tasks

# Default recipe - show available commands
default:
    @just --list

# Setup both Python and TypeScript environments
setup:
    @echo "🚀 Setting up full-stack environment..."
    @if [ -f "pyproject.toml" ]; then uv sync; fi
    @if [ -f "package.json" ]; then npm install; fi
    @echo "✅ Full-stack environment ready!"

# Python commands
py-run:
    uv run python src/main.py

py-test:
    uv run pytest

py-format:
    uv run black .
    uv run ruff check --fix .

# TypeScript commands
ts-dev:
    npx tsx watch src/index.ts

ts-build:
    npx tsc

ts-test:
    npm test

ts-format:
    npx prettier --write "src/**/*.{ts,js,json}"

# Universal commands
test:
    @echo "🧪 Running all tests..."
    @if [ -f "pyproject.toml" ]; then just py-test; fi
    @if [ -f "package.json" ]; then just ts-test; fi

format:
    @echo "💄 Formatting all code..."
    @if [ -f "pyproject.toml" ]; then just py-format; fi
    @if [ -f "package.json" ]; then just ts-format; fi

clean:
    @echo "🧹 Cleaning all artifacts..."
    @if [ -f "pyproject.toml" ]; then rm -rf .pytest_cache __pycache__ .mypy_cache .ruff_cache; fi
    @if [ -f "package.json" ]; then rm -rf node_modules dist .eslintcache; fi
