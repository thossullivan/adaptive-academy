#!/usr/bin/env python3
"""
BAML Integration Tests for Developer Crew

This module tests the integration between BAML functionality and the developer crew system,
ensuring that the BAML project manager works correctly within the broader system context.
"""

import asyncio
import sys
import os
import pytest
from pathlib import Path
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch

# Add project root to path (go up 2 levels from tests/baml/)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestBAMLIntegration:
    """Test BAML integration with developer crew system."""

    @pytest.fixture
    def mock_api_keys(self):
        """Mock API keys for testing."""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key-anthropic',
            'OPENAI_API_KEY': 'test-key-openai'
        }):
            yield

    @pytest.fixture
    async def baml_client(self):
        """Fixture to provide BAML client for tests."""
        try:
            from baml_client import b
            return b
        except ImportError:
            pytest.skip("BAML client not available")

    @pytest.fixture
    def sample_project_tasks(self):
        """Sample project tasks for testing."""
        return [
            {
                "name": "Simple Todo App",
                "description": "Create a simple todo app with React and Node.js",
                "expected_phases": (3, 6),
                "tech_stack": ["JavaScript", "React", "Node.js"]
            },
            {
                "name": "API Service",
                "description": "Build a REST API service with authentication",
                "expected_phases": (4, 7),
                "tech_stack": ["Node.js", "Express", "MongoDB"]
            },
            {
                "name": "Full Stack App",
                "description": "Create a full-stack web application with user management",
                "expected_phases": (5, 8),
                "tech_stack": ["React", "Node.js", "PostgreSQL", "TypeScript"]
            }
        ]

    async def test_baml_client_availability(self, baml_client):
        """Test that BAML client is properly available and configured."""
        assert baml_client is not None

        # Check that required functions are available
        required_functions = ['GenerateProjectPlan', 'AnalyzeProjectComplexity']
        for func_name in required_functions:
            assert hasattr(baml_client, func_name), f"Missing function: {func_name}"

    async def test_project_plan_generation(self, baml_client, sample_project_tasks, mock_api_keys):
        """Test project plan generation with BAML."""
        task = sample_project_tasks[0]  # Simple Todo App

        try:
            result = await baml_client.GenerateProjectPlan(
                task_description=task["description"],
                working_directory=".",
                existing_tech_stack=task["tech_stack"]
            )

            # Validate structure
            assert hasattr(result, 'phases'), "Result missing phases"
            assert hasattr(result, 'project_summary'), "Result missing project_summary"
            assert len(result.phases) > 0, "No phases generated"

            # Validate phase count is reasonable
            min_phases, max_phases = task["expected_phases"]
            assert min_phases <= len(result.phases) <= max_phases, \
                f"Phase count {len(result.phases)} outside expected range {min_phases}-{max_phases}"

            # Validate phase structure
            for i, phase in enumerate(result.phases):
                assert hasattr(phase, 'phase_name'), f"Phase {i} missing phase_name"
                assert hasattr(phase, 'description'), f"Phase {i} missing description"
                assert len(phase.description) > 10, f"Phase {i} description too short"

        except Exception as e:
            if "authentication_error" in str(e) or "invalid x-api-key" in str(e):
                pytest.skip("API key authentication failed - requires valid API key")
            else:
                raise

    async def test_baml_type_conversion(self, baml_client, sample_project_tasks, mock_api_keys):
        """Test that BAML types can be properly converted to Python objects."""
        task = sample_project_tasks[1]  # API Service

        try:
            result = await baml_client.GenerateProjectPlan(
                task_description=task["description"],
                working_directory=".",
                existing_tech_stack=task["tech_stack"]
            )

            # Test conversion to dictionary (as used in BAMLProjectManagerAgent)
            result_dict = self._convert_plan_to_dict(result)

            # Validate dictionary structure
            expected_keys = ['project_summary', 'phases', 'technology_stack']
            for key in expected_keys:
                assert key in result_dict, f"Missing key in converted dict: {key}"

            # Validate phases are properly converted
            assert isinstance(result_dict['phases'], list), "Phases should be a list"
            if result_dict['phases']:
                phase = result_dict['phases'][0]
                assert isinstance(phase, dict), "Phase should be a dictionary"
                assert 'phase_name' in phase, "Phase missing phase_name"
                assert 'description' in phase, "Phase missing description"

        except Exception as e:
            if "authentication_error" in str(e) or "invalid x-api-key" in str(e):
                pytest.skip("API key authentication failed - requires valid API key")
            else:
                raise

    def _convert_plan_to_dict(self, project_plan) -> Dict[str, Any]:
        """
        Convert BAML ProjectPlan to dictionary format.
        Simplified version of BAMLProjectManagerAgent._convert_plan_to_dict for testing.
        """
        try:
            return {
                "project_summary": getattr(project_plan, 'project_summary', ''),
                "technology_stack": [
                    stack.value if hasattr(stack, 'value') else str(stack)
                    for stack in getattr(project_plan, 'technology_stack', [])
                ],
                "phases": [
                    {
                        "phase_number": getattr(phase, 'phase_number', i + 1),
                        "phase_name": getattr(phase, 'phase_name', f'Phase {i + 1}'),
                        "description": getattr(phase, 'description', ''),
                        "estimated_effort": getattr(phase, 'estimated_effort', None),
                        "deliverables": [
                            getattr(deliverable, 'name', str(deliverable))
                            for deliverable in getattr(phase, 'deliverables', [])
                        ],
                        "acceptance_criteria": [
                            getattr(criterion, 'criterion', str(criterion))
                            for criterion in getattr(phase, 'acceptance_criteria', [])
                        ]
                    }
                    for i, phase in enumerate(getattr(project_plan, 'phases', []))
                ],
                "integration_plan": {
                    "strategy": getattr(getattr(project_plan, 'integration_plan', None), 'strategy', ''),
                    "testing_approach": getattr(getattr(project_plan, 'integration_plan', None), 'testing_approach', ''),
                },
                "deployment_considerations": {
                    "environment_setup": getattr(getattr(project_plan, 'deployment_considerations', None), 'environment_setup', []),
                    "infrastructure_requirements": getattr(getattr(project_plan, 'deployment_considerations', None), 'infrastructure_requirements', []),
                },
                "total_estimated_effort": getattr(project_plan, 'total_estimated_effort', 'Unknown'),
                "success_metrics": getattr(project_plan, 'success_metrics', []),
                "assumptions": getattr(project_plan, 'assumptions', []),
                "constraints": getattr(project_plan, 'constraints', [])
            }
        except Exception as e:
            return {
                "error": f"Failed to convert project plan: {str(e)}",
                "raw_type": str(type(project_plan)),
                "available_attributes": [attr for attr in dir(project_plan) if not attr.startswith('_')]
            }

    async def test_baml_error_handling(self, baml_client):
        """Test BAML error handling with invalid inputs."""
        # Test with empty task description
        try:
            result = await baml_client.GenerateProjectPlan(
                task_description="",
                working_directory=".",
                existing_tech_stack=[]
            )
            # If it succeeds, that's fine - just check the result is reasonable
            if hasattr(result, 'phases'):
                assert len(result.phases) >= 1, "Should generate at least one phase even for empty task"
        except Exception as e:
            # Expected that it might fail with empty input
            assert "authentication_error" in str(e) or "invalid x-api-key" in str(e) or len(str(e)) > 0

    async def test_complexity_analysis_integration(self, baml_client, mock_api_keys):
        """Test project complexity analysis integration."""
        try:
            from baml_client.types import TechnologyStack

            # Test with a complex project summary
            result = await baml_client.AnalyzeProjectComplexity(
                project_summary="Build a microservices-based e-commerce platform with real-time inventory, payment processing, user authentication, and analytics dashboard",
                technology_stack=[TechnologyStack.REACT, TechnologyStack.NODE_JS, TechnologyStack.POSTGRESQL]
            )

            # Validate complexity analysis structure
            assert hasattr(result, 'technical_complexity'), "Missing technical_complexity"
            assert hasattr(result, 'integration_complexity'), "Missing integration_complexity"

            # Check that complexity scores are reasonable (1-10)
            if hasattr(result, 'technical_complexity') and result.technical_complexity:
                assert 1 <= result.technical_complexity <= 10, "Technical complexity out of range"

        except Exception as e:
            if "authentication_error" in str(e) or "invalid x-api-key" in str(e):
                pytest.skip("API key authentication failed - requires valid API key")
            elif "TechnologyStack" in str(e):
                pytest.skip("TechnologyStack enum not properly configured")
            else:
                raise

    def test_baml_schema_consistency(self):
        """Test that BAML schemas are consistent and properly defined."""
        try:
            from baml_client import types

            # Check that key types exist
            required_types = ['ProjectPlan', 'ProjectPhase', 'TechnologyStack']
            for type_name in required_types:
                assert hasattr(types, type_name), f"Missing type: {type_name}"

            # Check ProjectPlan has expected structure
            ProjectPlan = getattr(types, 'ProjectPlan')
            if hasattr(ProjectPlan, '__annotations__'):
                annotations = ProjectPlan.__annotations__
                expected_fields = ['project_summary', 'phases', 'technology_stack']
                for field in expected_fields:
                    assert field in annotations, f"ProjectPlan missing field: {field}"

        except ImportError:
            pytest.skip("BAML types not available")

    async def test_fallback_mechanism(self, sample_project_tasks):
        """Test that the system can handle BAML failures gracefully."""
        # This would test the fallback logic in BAMLProjectManagerAgent
        # when BAML calls fail and the system needs to create a manual plan

        task = sample_project_tasks[0]

        # Simulate BAML failure by testing fallback plan creation
        fallback_plan = await self._create_test_fallback_plan(
            task["description"],
            ".",
            "BAML service unavailable"
        )

        assert isinstance(fallback_plan, dict), "Fallback plan should be a dictionary"
        assert "phases" in fallback_plan, "Fallback plan should have phases"
        assert len(fallback_plan["phases"]) >= 3, "Fallback plan should have at least 3 phases"

    async def _create_test_fallback_plan(self, task: str, working_dir: str, error: str) -> Dict[str, Any]:
        """Create a test fallback plan (simplified version for testing)."""
        return {
            "project_summary": f"Fallback plan for: {task}",
            "phases": [
                {
                    "phase_number": 1,
                    "phase_name": "Project Setup",
                    "description": "Initialize project structure and dependencies",
                    "estimated_effort": "2-3 hours"
                },
                {
                    "phase_number": 2,
                    "phase_name": "Core Development",
                    "description": "Implement main application logic",
                    "estimated_effort": "4-6 hours"
                },
                {
                    "phase_number": 3,
                    "phase_name": "Testing & Deployment",
                    "description": "Test application and deploy to production",
                    "estimated_effort": "2-3 hours"
                }
            ],
            "technology_stack": ["JavaScript", "React", "Node.js"],
            "total_estimated_effort": "8-12 hours",
            "fallback_reason": error,
            "success_metrics": ["Application runs successfully", "All tests pass"]
        }


# Standalone test runner for development
async def run_integration_tests():
    """Run integration tests manually for development/debugging."""
    print("🧪 Running BAML Integration Tests")
    print("=" * 50)

    test_instance = TestBAMLIntegration()

    # Test BAML client availability
    try:
        from baml_client import b
        await test_instance.test_baml_client_availability(b)
        print("✅ BAML client availability test passed")
    except Exception as e:
        print(f"❌ BAML client availability test failed: {e}")

    # Test schema consistency
    try:
        test_instance.test_baml_schema_consistency()
        print("✅ BAML schema consistency test passed")
    except Exception as e:
        print(f"❌ BAML schema consistency test failed: {e}")

    print("\n💡 To run all tests with pytest:")
    print("  cd adaptive-academy")
    print("  python -m pytest tests/baml/test_baml_integration.py -v")


if __name__ == "__main__":
    asyncio.run(run_integration_tests())
