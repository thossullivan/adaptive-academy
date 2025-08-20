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

## Development Phases

This is Phase 1 of the Developer Crew implementation:

- ✅ **Phase 1**: Foundation & The Coder Agent
  - Basic Coder agent with file system tools
  - Simple CLI interface
  - Code review capabilities

- 🚧 **Phase 2**: Adding Guardrails (Coming Next)
  - QA Tester agent with terminal tools
  - Orchestration workflow: Coder → Reviewer → Tester

- 📋 **Phase 3**: Full Crew Orchestration (Future)
  - Architect agent for high-level planning
  - Integrator agent as GroupChatManager
  - Full conversational workflow with feedback loops

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