# Adaptive Academy Documentation

Welcome to the comprehensive documentation for the Adaptive Academy project - an AI-powered personalized learning platform with automated development workflows.

## 📖 Documentation Overview

### Quick Start Guides

- **[Main README](../README.md)** - Project overview and quick start
- **[Developer Crew Quick Start](../developer_crew/README.md)** - AI development automation basics
- **[Development Guide](../CLAUDE.md)** - Development guidelines and conventions

### Core Components

#### 🤖 Developer Crew

AI-powered development automation with specialized agents.

- **[Complete Guide](developer-crew/README.md)** - Full documentation with examples and use cases
- **[Quick Reference](../developer_crew/README.md)** - Basic usage and commands

#### 🧠 BAML Integration

Type-safe AI interactions using Bounded AI Markup Language.

- **[BAML Overview](baml/README.md)** - Complete BAML integration guide
- **[Structure Guide](baml/structure.md)** - Project organization and file structure
- **[Prompt Refinement](baml/prompt-refinement.md)** - AI prompt engineering and optimization
- **[Demo Responses](baml/demo-responses.md)** - Example AI responses and outputs

#### Examples & Artifacts

- **[Example Outputs](examples/)** - Sample project plans, BAML test results, and configuration examples

### Testing & Validation

#### Test Suites

- **[BAML Tests](../tests/baml/)** - BAML functionality and integration tests
- **[Developer Crew Tests](../tests/developer_crew/)** - Agent testing and validation
- **[Frontend Tests](../tests/frontend/)** - UI component and integration tests
- **[Backend Tests](../tests/backend/)** - API endpoint and service tests

#### Quality Assurance

- Run all tests: `uv run pytest`
- BAML specific tests: `python -m pytest tests/baml/ -v`
- Developer crew tests: `python -m pytest tests/developer_crew/ -v`

### Project Structure

```
adaptive-academy/
├── docs/                           # 📚 This documentation
│   ├── baml/                      # BAML integration docs
│   └── developer-crew/            # Developer crew docs
├── developer_crew/                # 🤖 AI development automation
├── baml_src/                      # 🧠 BAML schemas and functions
├── baml_client/                   # 🔄 Generated BAML client
├── frontend/                      # 🎨 Next.js UI application
├── backend/                       # 🔧 FastAPI service
├── tests/                         # 🧪 Comprehensive test suite
├── scripts/                       # 🛠️ Utility and analysis scripts
├── shared/                        # 📦 Common code and resources
└── docs/examples/                 # 📋 Example outputs and configurations
```

## 🚀 Getting Started

### Prerequisites

- Python 3.12+ with `uv` package manager
- Node.js 18+ with npm
- API key for AI providers (Anthropic, OpenAI, or Google)

### Initial Setup

```bash
# 1. Install Python dependencies
uv sync

# 2. Install Node.js dependencies
cd frontend && npm install && cd ..

# 3. Set up environment variables
echo "ANTHROPIC_API_KEY=your_key_here" >> .env

# 4. Test setup
uv run python -m developer_crew.main setup-test
```

### Common Workflows

#### AI-Powered Development

```bash
# Generate project plan
uv run python -m developer_crew.main plan "Create a user dashboard"

# Full development workflow
uv run python -m developer_crew.main workflow "Add authentication system"

# Individual agents
uv run python -m developer_crew.main code "Create login component"
uv run python -m developer_crew.main review ./src/components/Login.tsx
uv run python -m developer_crew.main test ./src
```

#### BAML Testing

```bash
# Test BAML client functionality
python tests/baml/test_baml_client.py

# Test API key setup
python tests/baml/test_api_key_setup.py

# Run full BAML test suite
python -m pytest tests/baml/ -v
```

## 🎯 Development Status

### ✅ Completed Components

- **Developer Crew**: 4 specialized AI agents (Coder, Reviewer, Tester, Project Manager)
- **BAML Integration**: Type-safe AI interactions with structured output
- **Multi-Provider AI**: Support for Anthropic, OpenAI, and Google models
- **Testing Framework**: Comprehensive test coverage for all components

### 🚧 In Progress

- **BAML Prompt Optimization**: Refining AI prompts for better structured responses
- **Learning Platform**: Building the core educational application
- **Advanced Agents**: Business Analyst, DevOps, Security, and Documentation agents

### 🔮 Planned

- **Real-time Collaboration**: Multi-developer workflow support
- **Enterprise Features**: Advanced project management and team coordination
- **Performance Optimization**: Automated code performance improvements

## 🤝 Contributing

### Development Guidelines

1. **Follow the structure**: Use the organized documentation and test structure
2. **Test everything**: Ensure new features have comprehensive tests
3. **Document changes**: Update relevant documentation for any modifications
4. **Use the tools**: Leverage Developer Crew for consistent code generation

### Code Quality

- **Linting**: `uv run ruff check && uv run black --check .`
- **Type checking**: `uv run mypy .`
- **Testing**: `uv run pytest`

### Documentation Standards

- Keep READMEs concise and focused on usage
- Place comprehensive documentation in `docs/`
- Include examples and code snippets
- Update documentation with any structural changes

## 📞 Support

### Common Issues

- **Import errors**: Check BAML client generation with `baml-cli generate`
- **API failures**: Verify API keys are correctly set in `.env`
- **Test failures**: Ensure all dependencies are installed with `uv sync`

### Resources

- **[GitHub Issues](https://github.com/your-org/adaptive-academy/issues)** - Bug reports and feature requests
- **[BAML Documentation](https://docs.boundaryml.com)** - Official BAML documentation
- **[AutoGen Documentation](https://microsoft.github.io/autogen/)** - Multi-agent framework documentation

---

**Last Updated**: August 2024
**Version**: 1.0.0
**Status**: Active Development
