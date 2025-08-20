# BAML Integration Documentation

## Overview

BAML (Bounded AI Markup Language) provides type-safe AI interactions for the Adaptive Academy project. This directory contains comprehensive documentation for understanding, using, and extending the BAML integration.

## Quick Start

```bash
# Install dependencies
pip install baml baml-py

# Set up API key
export ANTHROPIC_API_KEY="your_key_here"

# Generate BAML client
cd adaptive-academy
baml-cli generate

# Test BAML functionality
python -m pytest tests/baml/ -v
```

## Documentation Structure

### Core Documentation
- **[structure.md](structure.md)** - Complete BAML project structure and organization
- **[demo-responses.md](demo-responses.md)** - Example AI responses and expected outputs
- **[prompt-refinement.md](prompt-refinement.md)** - Prompt engineering notes and improvements

### Key Components

#### BAML Schemas (`baml_src/`)
- **learning_schemas.baml** - All BAML type definitions and functions
- **generators.baml** - Client generation configuration

#### Generated Client (`baml_client/`)
- Auto-generated Python client (DO NOT EDIT)
- Provides type-safe AI function calls
- Regenerate with `baml-cli generate`

#### Integration Layer (`developer_crew/`)
- **baml_project_manager.py** - Main BAML wrapper for project planning
- **baml_project_manager_simple.py** - Simplified version for testing

## Key Functions

### Project Planning
```python
from baml_client import b

result = await b.GenerateProjectPlan(
    task_description="Create a todo app",
    working_directory=".",
    existing_tech_stack=["JavaScript", "React"]
)
```

### Project Complexity Analysis
```python
complexity = await b.AnalyzeProjectComplexity(
    project_summary="Complex e-commerce platform",
    technology_stack=[TechnologyStack.REACT, TechnologyStack.NODE_JS]
)
```

## Testing

### Test Structure
```
tests/baml/
├── test_baml_client.py       # Direct BAML client tests
├── test_baml_prompts.py      # Prompt engineering tests
├── test_baml_integration.py  # Integration with developer crew
└── test_api_key_setup.py     # API key configuration tests
```

### Running Tests
```bash
# All BAML tests
python -m pytest tests/baml/ -v

# Specific test categories
python -m pytest tests/baml/test_baml_client.py -v
python -m pytest tests/baml/test_baml_prompts.py -v

# With API key validation
ANTHROPIC_API_KEY=your_key python -m pytest tests/baml/ -v
```

## Current Status

- ✅ **Project Structure**: Clean and organized
- ✅ **BAML Client**: Generated and importable
- ✅ **Schema Validation**: All types properly available
- ✅ **API Integration**: Anthropic Claude working
- ⚠️ **Response Parsing**: Working on structured output optimization
- 🎯 **Next Phase**: Prompt refinement for consistent structured responses

## Common Issues & Solutions

### Import Errors
```python
# ✅ Correct
from baml_client import b, types
from baml_client.types import ProjectPlan

# ❌ Incorrect
from baml_client.baml_client import b
```

### Client Regeneration
```bash
# If schema changes
cd adaptive-academy
baml-cli generate
```

### API Key Setup
```bash
# Required environment variable
export ANTHROPIC_API_KEY="sk-ant-..."

# Or in .env file
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

## Development Workflow

1. **Modify Schemas**: Edit `baml_src/learning_schemas.baml`
2. **Regenerate Client**: Run `baml-cli generate`
3. **Test Changes**: Run `python -m pytest tests/baml/ -v`
4. **Update Integration**: Modify `developer_crew/baml_project_manager.py` if needed
5. **Document Changes**: Update relevant documentation

## Contributing

When making changes to BAML integration:

1. **Test First**: Ensure existing tests pass
2. **Schema Changes**: Always regenerate client after schema modifications
3. **Documentation**: Update relevant docs in this directory
4. **Integration**: Test with the full developer crew system
5. **Examples**: Add examples to demo-responses.md for complex changes

## Support

- **BAML Documentation**: https://docs.boundaryml.com
- **Issues**: Create GitHub issues for BAML-specific problems
- **Testing**: Use `tests/baml/` for validation and debugging

## Version Info

- **BAML Version**: 0.205.0
- **Python Client**: baml-py==0.205.0
- **Primary AI Provider**: Anthropic Claude-3.5-Sonnet
