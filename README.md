# 🎓 Adaptive Academy

AI-powered personalized learning platform with automated development workflows.

## 🏗️ Modern Monorepo Structure

This project is organized by function for maximum clarity and scalability:

```
adaptive-academy/                    # Monorepo root
├── frontend/                       # Next.js/TypeScript UI
├── backend/                        # FastAPI Python service
├── developer_crew/                 # AI development automation tools
├── baml_src/                       # BAML AI schemas & functions
├── baml_client/                    # Generated BAML client (auto-generated)
├── shared/                         # Common code & schemas
│   ├── types/                      # Shared TypeScript/Python types
│   └── database/                   # Database schemas & SQLite
├── docs/                           # Comprehensive documentation
│   ├── baml/                       # BAML integration docs
│   └── developer-crew/             # Developer crew docs
├── tests/                          # Centralized test suite
│   ├── frontend/
│   ├── backend/
│   ├── developer_crew/
│   └── baml/                       # BAML functionality tests
└── scripts/                        # Utility scripts and analysis
```

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- uv (Python package manager)

### Setup

1. **Install Python dependencies:**

```bash
uv sync
```

2. **Install Node.js dependencies:**

```bash
cd frontend && npm install
```

### Development Commands

**🤖 Developer Crew (AI Development Tools)**

```bash
# Set up API key
echo "ANTHROPIC_API_KEY=your_key_here" >> .env

# Test setup
uv run python -m developer_crew.main setup-test

# Generate comprehensive project plans
uv run python -m developer_crew.main plan "Create a todo app with React and Node.js"

# Full development workflow (Code → Review → Test)
uv run python -m developer_crew.main workflow "Add user authentication"
uv run dev-crew code "Create a user authentication endpoint"

# Run full workflow (code → review → test)
uv run dev-crew workflow "Build a user profile component"
```

**🔧 Backend Development**

```bash
# Run FastAPI server
uv run backend

# Run with auto-reload (development)
cd backend && uvicorn main:app --reload
```

**🎨 Frontend Development**

```bash
cd frontend
npm run dev
```

**🧪 Testing**

```bash
# Run all tests
uv run pytest

# Run specific test suites
uv run pytest tests/developer_crew/
uv run pytest tests/backend/
```

## 📖 Two-Part Development Strategy

### Part 1: Developer Crew ✅ **COMPLETED**

AI agents that automate software development tasks:

- **CoderAgent**: Writes and modifies code with file system access
- **CodeReviewerAgent**: Reviews code quality and best practices
- **QA_TesterAgent**: Tests and validates code through execution

**Status**: Fully operational with rich CLI and complete workflow orchestration.

### Part 2: Learning Application 🏗️ **IN PROGRESS**

The personalized learning platform built using the Developer Crew:

- **CurriculumDirector**: Plans learning paths and sequences topics
- **TutorAgent**: Provides interactive instruction and explanations
- **AssessmentCoach**: Creates assessments and evaluates progress

## 🏛️ Architecture

### Hybrid Full-Stack Design

- **Frontend**: Next.js/TypeScript for modern UI/UX
- **Backend**: FastAPI with AI agents for personalized learning
- **Database**: SQLite for local development, PostgreSQL-ready for production
- **AI Integration**: BAML for type-safe LLM interactions
- **Agent Orchestration**: Microsoft AutoGen for conversational AI workflows

### BAML Integration Strategy

BAML provides end-to-end type safety between Python backend and TypeScript frontend:

1. **Define in BAML**: Create functions and schemas in `.baml` files
2. **Generate Code**: Run `baml build` to generate typed clients
3. **Orchestrate in Python**: Agents use BAML functions as tools
4. **Consume in TypeScript**: Frontend uses generated types

Example BAML functions:

```baml
function GenerateCurriculum(topic: string, user_profile: LearningProfile) -> Curriculum
function CreateQuiz(topic: string, difficulty: int, question_count: int) -> Quiz
function ExplainConcept(concept: string, context: string) -> Explanation
```

## 🛠️ Available Commands

```bash
# Development tools
uv run dev-crew --help           # See all developer crew commands
uv run backend --help            # FastAPI server options

# Testing & Quality
uv run pytest -v                # Verbose test output
uv run pytest --cov             # With coverage
uv run ruff check               # Linting
uv run black .                  # Formatting
uv run mypy .                   # Type checking

# Development dependencies
uv sync --group developer-crew   # Install AI development tools
```

## 🗂️ Key Files & Directories

- **`CLAUDE.md`**: Design principles and development guidelines
- **`MVP_EXECUTION_PLAN.md`**: Detailed implementation roadmap
- **`developer_crew/`**: AI development automation (Part 1)
- **`backend/agents/`**: Learning platform agents (Part 2)
- **`shared/database/`**: SQLite database and schemas
- **`tests/`**: Comprehensive test suite for all components

## 🚀 Current Status

### ✅ **Phase 1 & 2: Developer Crew - COMPLETED**

- Three-agent pipeline (Coder → Reviewer → Tester)
- Rich CLI with individual and workflow commands
- Comprehensive file system and execution tools
- Modern AutoGen 0.7.4 integration
- Complete test coverage

### 🏗️ **Phase 3: Learning Application - IN PROGRESS**

- Backend FastAPI service scaffolded
- Agent structure ready for implementation
- Database schema designed
- Frontend-backend communication planned

## 📚 Documentation

### Core Documentation

- **[Project Overview](README.md)** - This file, main project documentation
- **[Development Guide](CLAUDE.md)** - Detailed development guidelines and conventions

### Component Documentation

- **[Developer Crew](docs/developer-crew/README.md)** - Complete AI development automation guide
    - Quick start: [developer_crew/README.md](developer_crew/README.md)
- **[BAML Integration](docs/baml/README.md)** - Type-safe AI interactions documentation
    - Structure guide: [docs/baml/structure.md](docs/baml/structure.md)
    - Prompt refinement: [docs/baml/prompt-refinement.md](docs/baml/prompt-refinement.md)
    - Demo responses: [docs/baml/demo-responses.md](docs/baml/demo-responses.md)

### Testing Documentation

- **[BAML Tests](tests/baml/)** - BAML functionality testing
- **[Developer Crew Tests](tests/developer_crew/)** - Agent testing and validation
- **[Frontend Tests](tests/frontend/)** - UI component testing
- **[Backend Tests](tests/backend/)** - API endpoint testing

### Project Plans and Analysis

- **[MVP Execution Plan](MVP_EXECUTION_PLAN.md)** - Detailed project roadmap
- **[Analysis Scripts](scripts/)** - BAML analysis and utility scripts

## 🤝 Contributing

1. **Run tests**: `uv run pytest`
2. **Check code quality**: `uv run ruff check && uv run black --check .`
3. **Use Developer Crew**: `uv run dev-crew workflow "describe your feature"`
4. **Follow conventions**: See `CLAUDE.md` for detailed guidelines
5. **Documentation**: Update relevant docs in `docs/` when making changes

---

**Built with modern tools**: FastAPI • Next.js • AutoGen • BAML • SQLite • UV Package Manager
