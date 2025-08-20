# BAML Project Structure Documentation

## Overview

This document outlines the cleaned and organized structure for BAML (Bounded AI Markup Language) integration in the Adaptive Academy project.

## Directory Structure

```
adaptive-academy/
├── baml_src/                    # ✅ BAML Source Files (Primary)
│   ├── generators.baml          # BAML client generation config
│   └── learning_schemas.baml    # All BAML schemas and functions
├── baml_client/                 # ✅ Auto-generated BAML Client
│   ├── __init__.py             # Package initialization
│   └── baml_client/            # Generated Python client code
├── tests/
│   └── baml/                   # ✅ BAML Tests (Organized)
│       ├── __init__.py         # Test package init
│       ├── test_baml_client.py # Direct BAML client tests
│       ├── test_baml_prompts.py # Prompt engineering tests
│       └── test_baml_integration.py # Integration with developer crew
├── scripts/                    # ✅ Utility Scripts
│   └── analyze_baml_prompts.py # BAML analysis utilities
└── developer_crew/
    ├── baml_project_manager.py # BAML integration wrapper
    └── baml_project_manager_simple.py # Simplified version
```

## What Was Cleaned Up

### ❌ Removed Redundancy:
- **`./shared/baml/`** - Duplicate schemas (identical to `baml_src/`)
- **Root-level test files** - Moved to proper test directory:
  - `test_baml_isolated.py` → `tests/baml/test_baml_client.py`
  - `test_baml_with_auth.py` → `tests/baml/test_baml_prompts.py`
  - `test_baml_standalone.py` → Deleted (redundant)
  - `test_baml_project_manager.py` → Deleted (redundant)

### ✅ Organized Structure:
- **Single source of truth**: `baml_src/` contains all BAML schemas
- **Proper test organization**: All BAML tests in `tests/baml/`
- **Utilities separated**: Analysis scripts in `scripts/`

## File Purposes

### Core BAML Files

#### `baml_src/learning_schemas.baml`
- **Purpose**: Defines all BAML schemas, enums, and functions
- **Key Functions**:
  - `GenerateProjectPlan()` - Main project planning function
  - `AnalyzeProjectComplexity()` - Project complexity analysis
  - `GetProjectTemplate()` - Template selection
- **Key Types**:
  - `ProjectPlan` - Complete project structure
  - `ProjectPhase` - Individual project phases
  - `TechnologyStack` - Technology enums

#### `baml_src/generators.baml`
- **Purpose**: Configures BAML client generation
- **Settings**: Python/Pydantic output to `baml_client/`

### Generated Client

#### `baml_client/`
- **Purpose**: Auto-generated Python client (DO NOT EDIT MANUALLY)
- **Regenerate with**: `baml-cli generate`
- **Usage**: `from baml_client import b, types`

### Test Files

#### `tests/baml/test_baml_client.py`
- **Purpose**: Test direct BAML client functionality
- **Tests**: Imports, schema validation, basic function calls

#### `tests/baml/test_baml_prompts.py`
- **Purpose**: Test prompt engineering and response quality
- **Tests**: Different scenarios, prompt variations, quality analysis

#### `tests/baml/test_baml_integration.py`
- **Purpose**: Test BAML integration with developer crew system
- **Tests**: End-to-end workflows, error handling, fallback mechanisms

### Integration Files

#### `developer_crew/baml_project_manager.py`
- **Purpose**: Main BAML integration wrapper for developer crew
- **Features**:
  - Structured project plan generation
  - Error handling and fallbacks
  - Type conversion utilities

#### `developer_crew/baml_project_manager_simple.py`
- **Purpose**: Simplified version for testing/debugging
- **Use**: When full integration is not needed

## Regenerating BAML Client

When you modify `baml_src/*.baml` files:

```bash
cd adaptive-academy
baml-cli generate
```

This updates the `baml_client/` directory with new Python types and functions.

## Running Tests

```bash
# Run all BAML tests
python -m pytest tests/baml/ -v

# Run specific test files
python -m pytest tests/baml/test_baml_client.py -v
python -m pytest tests/baml/test_baml_prompts.py -v
python -m pytest tests/baml/test_baml_integration.py -v

# Run individual test files directly (for development)
cd adaptive-academy
python tests/baml/test_baml_client.py
```

## API Key Configuration

Tests requiring AI model access need environment variables:

```bash
export ANTHROPIC_API_KEY="your_anthropic_key"
export OPENAI_API_KEY="your_openai_key"
export GOOGLE_API_KEY="your_google_key"
```

## Best Practices

### ✅ Do:
- Keep all BAML schemas in `baml_src/learning_schemas.baml`
- Use proper test organization in `tests/baml/`
- Regenerate client after schema changes
- Use type hints from `baml_client.types`

### ❌ Don't:
- Edit `baml_client/` manually (it's auto-generated)
- Create duplicate BAML schemas in multiple locations
- Put test files in project root
- Commit without running tests

## Current Status

- ✅ **Structure Cleaned**: Redundant files removed, proper organization
- ✅ **Tests Organized**: All BAML tests in proper directory structure
- ✅ **Client Generated**: BAML client properly generated and importable
- ⚠️  **API Keys Needed**: For full testing functionality
- 🎯 **Next Steps**: Refine prompts and improve response quality

## Troubleshooting

### Import Errors
```python
# ✅ Correct imports
from baml_client import b, types
from baml_client.types import ProjectPlan, ProjectPhase

# ❌ Incorrect imports
from baml_client.baml_client import b  # Wrong path
```

### Client Generation Issues
```bash
# If baml-cli not found:
pip install baml baml-py

# If generation fails:
cd adaptive-academy
/path/to/baml-cli generate  # Use full path if needed
```

### Test Import Issues
```python
# Tests should use relative project root:
project_root = Path(__file__).parent.parent.parent  # For tests/baml/
sys.path.insert(0, str(project_root))
```

This structure provides a clean, maintainable foundation for BAML development and testing.
