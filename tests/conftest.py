"""Shared pytest configuration and fixtures for all tests."""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def sample_python_file():
    """Create a sample Python file for testing."""
    content = '''"""Sample Python module for testing."""

def hello_world():
    """Print hello world."""
    print("Hello, World!")
    return "Hello, World!"


def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    hello_world()
'''
    return content


@pytest.fixture
def project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def developer_crew_root(project_root):
    """Get the developer_crew directory."""
    return project_root / "developer_crew"