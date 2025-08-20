# Developer Crew

AI-powered software development automation using specialized agents.

## Overview

Developer Crew is an internal tool for the Adaptive Academy project that automates software development tasks using AI agents. It's designed to accelerate development by providing specialized AI agents that can write, review, and test code.

## Agents

### 🤖 Coder Agent
- Writes clean, maintainable code
- Follows existing patterns and conventions
- Implements features according to specifications
- Has access to file system tools (read, write, edit)

### 👁️ Code Reviewer Agent  
- Reviews code for quality and best practices
- Identifies bugs and potential issues
- Suggests improvements for maintainability
- Has read-only access to codebase

### 🧪 QA Tester Agent (**New in Phase 2**)
- Executes code to verify functionality
- Runs automated tests (pytest, unittest, nose)
- Performs code quality checks (ruff, mypy, black, flake8)
- Validates runtime behavior and performance
- Provides comprehensive test reports with recommendations

## Installation

```bash
# Install dependencies (using modern uv package manager)
uv sync

# Initialize project configuration
uv run python -m developer_crew.main init
```

## Configuration

1. Set your OpenAI API key in the generated `.env` file:
```
OPENAI_API_KEY=your-api-key-here
```

2. Test your setup:
```bash
uv run python -m developer_crew.main test
```

## Usage

### Code Generation
```bash
# Generate code with a task description
uv run python -m developer_crew.main code "Create a simple FastAPI health check endpoint"

# Specify working directory
uv run python -m developer_crew.main code "Add error handling to user authentication" --working-dir ./src

# Use different model
uv run python -m developer_crew.main code "Refactor database queries" --model gpt-3.5-turbo
```

### Code Review
```bash
# Review a specific file
uv run python -m developer_crew.main review src/main.py

# Use different model for review
uv run python -m developer_crew.main review src/models.py --model gpt-4
```

### Testing & Validation (**New in Phase 2**)
```bash
# Test a specific file or directory
uv run python -m developer_crew.main test src/main.py

# Test entire project
uv run python -m developer_crew.main test . --working-dir ./my-project

# Use different model for testing
uv run python -m developer_crew.main test tests/ --model gpt-3.5-turbo
```

### Full Development Workflow (**New in Phase 2**)
```bash
# Run complete workflow: Code -> Review -> Test
uv run python -m developer_crew.main workflow "Create a calculator class with add, subtract, multiply methods"

# Skip specific phases
uv run python -m developer_crew.main workflow "Fix bug in authentication" --skip-review

# Custom working directory
uv run python -m developer_crew.main workflow "Add logging to user service" --working-dir ./backend
```

## Development Phases

- ✅ **Phase 1**: Foundation & The Coder Agent (**COMPLETED**)
  - Coder agent with comprehensive file system tools
  - Code Reviewer agent for static analysis
  - Rich CLI interface with individual agent commands
  - Modern AutoGen 0.7.4 async API integration

- ✅ **Phase 2**: Adding Guardrails & Orchestration (**COMPLETED**)
  - QA Tester agent with secure terminal execution
  - Full three-agent orchestration pipeline
  - Comprehensive testing framework integration
  - Complete workflow command with customizable phases

- 📋 **Phase 3**: Full Crew Orchestration (Future)
  - Architect agent for high-level planning
  - Integrator agent as GroupChatManager
  - Advanced conversational workflows with iterative feedback
  - Multi-agent collaboration and conflict resolution

## Project Structure

```
developer_crew/
├── developer_crew/           # Main package
│   ├── __init__.py
│   ├── agents.py            # AI agent implementations
│   ├── tools.py             # File system tools
│   └── main.py              # CLI interface
├── tests/                   # Test suite (coming soon)
├── pyproject.toml          # Project configuration
└── README.md               # This file
```

## Contributing

This tool is part of the Adaptive Academy project's development workflow. See the main project documentation for contribution guidelines.