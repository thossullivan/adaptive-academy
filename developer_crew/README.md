# Developer Crew - Quick Start

AI-powered development automation with specialized agents for coding, review, and testing.

## Quick Setup

```bash
# Install dependencies
uv sync --group developer-crew

# Set API key in .env
echo "ANTHROPIC_API_KEY=your_key_here" >> .env

# Test setup
uv run python -m developer_crew.main setup-test
```

## Basic Usage

### Project Planning

```bash
# Generate comprehensive project plan
uv run python -m developer_crew.main plan "Create a todo app with React and Node.js"
```

### Full Workflow (Code → Review → Test)

```bash
# Complete development cycle
uv run python -m developer_crew.main workflow "Add user authentication to the app"
```

### Individual Agents

```bash
# Code generation
uv run python -m developer_crew.main code "Create a React login component"

# Code review
uv run python -m developer_crew.main review ./src/components/Login.tsx

# Testing & validation
uv run python -m developer_crew.main test ./src
```

## Key Features

- **🤖 Multi-Provider AI**: Anthropic Claude, OpenAI GPT, Google Gemini
- **📋 Intelligent Planning**: Break complex projects into phases
- **🔄 Complete Workflow**: Automated code generation, review, testing
- **🛡️ Production Ready**: Enterprise-scale project handling

## Agents

- **💻 Coder Agent**: Writes clean, maintainable code
- **👁️ Code Reviewer**: Reviews for quality and best practices
- **🧪 QA Tester**: Executes tests and validates functionality
- **📋 Project Manager**: Creates detailed project plans

## Documentation

For comprehensive documentation, see:

- **[Complete Guide](../docs/developer-crew/README.md)** - Full documentation with examples
- **[BAML Integration](../docs/baml/README.md)** - Type-safe AI interactions
- **[Testing Guide](../tests/developer_crew/README.md)** - Testing and validation

## Support

- Run `uv run python -m developer_crew.main --help` for all commands
- Check [issues](https://github.com/your-org/adaptive-academy/issues) for troubleshooting
- See [docs/developer-crew/](../docs/developer-crew/) for detailed guides
