#!/usr/bin/env python3
"""
BAML API Key Configuration and Prompt Testing
Tests BAML functionality with proper API key setup and prompt refinement.
"""

import asyncio
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path (go up 2 levels from tests/baml/)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def setup_api_keys():
    """Setup API keys for testing BAML functionality."""
    print("🔑 Setting up API keys...")

    # Check for existing API keys
    api_keys = {
        'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY'),
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
        'GOOGLE_API_KEY': os.getenv('GOOGLE_API_KEY')
    }

    available_keys = {k: v for k, v in api_keys.items() if v}

    if available_keys:
        print(f"✅ Found API keys: {list(available_keys.keys())}")
        return True
    else:
        print("❌ No API keys found in environment variables")
        print("\nTo test BAML functionality, please set one of:")
        print("  export ANTHROPIC_API_KEY='your_key_here'")
        print("  export OPENAI_API_KEY='your_key_here'")
        print("  export GOOGLE_API_KEY='your_key_here'")
        return False

async def test_baml_with_different_prompts():
    """Test BAML with various prompt refinements."""
    print("\n🧪 Testing BAML with different prompt approaches...")

    try:
        from baml_client import b, types

        # Test cases with different complexity levels
        test_cases = [
            {
                "name": "Simple Todo App",
                "task": "Create a simple todo app with React and Node.js",
                "expected_phases": 4-6
            },
            {
                "name": "E-commerce Platform",
                "task": "Build a full e-commerce platform with user authentication, product catalog, shopping cart, and payment processing",
                "expected_phases": 6-8
            },
            {
                "name": "Real-time Chat App",
                "task": "Develop a real-time chat application with WebSocket support, user rooms, and message history",
                "expected_phases": 5-7
            }
        ]

        results = []

        for test_case in test_cases:
            print(f"\n📋 Testing: {test_case['name']}")
            print(f"Task: {test_case['task']}")

            try:
                result = await b.GenerateProjectPlan(
                    task_description=test_case['task'],
                    working_directory=".",
                    existing_tech_stack=["JavaScript", "React", "Node.js"]
                )

                # Analyze the result
                analysis = analyze_project_plan_result(result, test_case)
                results.append(analysis)

                print(f"✅ Generated plan with {len(result.phases)} phases")
                print(f"📊 Quality Score: {analysis['quality_score']}/10")

                # Show first phase as example
                if result.phases:
                    first_phase = result.phases[0]
                    print(f"📌 Example Phase: {first_phase.phase_name}")
                    print(f"   Description: {first_phase.description[:100]}...")

            except Exception as e:
                print(f"❌ Failed for {test_case['name']}: {str(e)}")
                results.append({
                    "test_case": test_case['name'],
                    "success": False,
                    "error": str(e),
                    "quality_score": 0
                })

        return results

    except Exception as e:
        print(f"❌ BAML testing failed: {str(e)}")
        return []

def analyze_project_plan_result(result, test_case: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze the quality of a generated project plan."""
    analysis = {
        "test_case": test_case['name'],
        "success": True,
        "quality_score": 0,
        "issues": [],
        "strengths": []
    }

    try:
        # Check basic structure
        if not hasattr(result, 'phases') or not result.phases:
            analysis['issues'].append("No phases generated")
            return analysis

        phase_count = len(result.phases)
        expected_range = test_case.get('expected_phases', (3, 8))

        # Scoring criteria
        score = 0

        # Phase count appropriateness (2 points)
        if isinstance(expected_range, tuple):
            min_phases, max_phases = expected_range
        else:
            min_phases, max_phases = expected_range - 1, expected_range + 1

        if min_phases <= phase_count <= max_phases:
            score += 2
            analysis['strengths'].append(f"Appropriate phase count: {phase_count}")
        else:
            analysis['issues'].append(f"Phase count {phase_count} outside expected range {min_phases}-{max_phases}")

        # Check phase structure quality (2 points per phase, max 6)
        phase_structure_score = 0
        for i, phase in enumerate(result.phases[:3]):  # Check first 3 phases
            phase_score = 0

            # Check required fields
            if hasattr(phase, 'phase_name') and phase.phase_name:
                phase_score += 0.5
            if hasattr(phase, 'description') and phase.description and len(phase.description) > 20:
                phase_score += 0.5
            if hasattr(phase, 'deliverables') and phase.deliverables:
                phase_score += 0.5
            if hasattr(phase, 'acceptance_criteria') and phase.acceptance_criteria:
                phase_score += 0.5

            phase_structure_score += min(phase_score, 2)

        score += min(phase_structure_score, 6)

        # Check for project summary (1 point)
        if hasattr(result, 'project_summary') and result.project_summary:
            score += 1
            analysis['strengths'].append("Has project summary")
        else:
            analysis['issues'].append("Missing project summary")

        # Check for integration plan (1 point)
        if hasattr(result, 'integration_plan') and result.integration_plan:
            score += 1
            analysis['strengths'].append("Has integration plan")
        else:
            analysis['issues'].append("Missing integration plan")

        analysis['quality_score'] = score

        # Additional analysis
        if score >= 8:
            analysis['strengths'].append("High-quality comprehensive plan")
        elif score >= 6:
            analysis['strengths'].append("Good plan structure")
        elif score >= 4:
            analysis['strengths'].append("Basic plan requirements met")
        else:
            analysis['issues'].append("Plan needs significant improvement")

    except Exception as e:
        analysis['success'] = False
        analysis['error'] = str(e)

    return analysis

async def test_prompt_variations():
    """Test different prompt variations to optimize BAML responses."""
    print("\n🔧 Testing prompt variations...")

    # This would test different prompt engineering approaches
    prompt_variations = [
        {
            "name": "Current Prompt",
            "description": "Using existing BAML prompt"
        },
        {
            "name": "More Structured",
            "description": "Enhanced with explicit formatting requirements"
        },
        {
            "name": "Examples-Based",
            "description": "Including concrete examples in prompt"
        }
    ]

    print("📝 Prompt variations to test:")
    for i, variation in enumerate(prompt_variations, 1):
        print(f"  {i}. {variation['name']}: {variation['description']}")

    return prompt_variations

def suggest_prompt_improvements():
    """Suggest specific improvements to BAML prompts based on testing."""
    print("\n💡 BAML Prompt Improvement Suggestions:")

    improvements = [
        {
            "area": "Structure Enforcement",
            "suggestion": "Add explicit JSON schema validation instructions",
            "example": "Ensure each phase has exactly these fields: phase_number, phase_name, description, deliverables..."
        },
        {
            "area": "Content Quality",
            "suggestion": "Add specific guidance for deliverable detail level",
            "example": "Each deliverable should be specific enough to be testable (e.g., 'User can add todo items' not 'Basic functionality')"
        },
        {
            "area": "Consistency",
            "suggestion": "Include examples of well-formed phases",
            "example": "Example Phase: {phase_name: 'Backend API Setup', description: 'Create Express.js server...', deliverables: ['REST API endpoints', 'Database schema']}"
        },
        {
            "area": "Error Handling",
            "suggestion": "Add fallback instructions for complex tasks",
            "example": "If task is too complex, break into 8 phases. If too simple, combine into 3-4 phases."
        },
        {
            "area": "Technology Awareness",
            "suggestion": "Better integration of existing tech stack",
            "example": "Leverage existing {{existing_tech_stack}} and suggest complementary technologies only when necessary"
        }
    ]

    for improvement in improvements:
        print(f"\n🎯 {improvement['area']}:")
        print(f"   Suggestion: {improvement['suggestion']}")
        print(f"   Example: {improvement['example']}")

    return improvements

async def main():
    """Main testing function."""
    print("🩺 BAML API Key Configuration and Prompt Testing")
    print("=" * 60)

    # Step 1: Check API keys
    if not setup_api_keys():
        print("\n⚠️  Cannot test BAML functionality without API keys")
        print("Please set up API keys and run again.")
        return

    # Step 2: Test BAML with different scenarios
    test_results = await test_baml_with_different_prompts()

    # Step 3: Analyze results
    if test_results:
        print("\n📊 Test Results Summary:")
        successful_tests = [r for r in test_results if r.get('success', False)]
        total_score = sum(r.get('quality_score', 0) for r in successful_tests)
        avg_score = total_score / len(successful_tests) if successful_tests else 0

        print(f"✅ Successful tests: {len(successful_tests)}/{len(test_results)}")
        print(f"📈 Average quality score: {avg_score:.1f}/10")

        # Show issues and strengths
        all_issues = []
        all_strengths = []
        for result in successful_tests:
            all_issues.extend(result.get('issues', []))
            all_strengths.extend(result.get('strengths', []))

        if all_issues:
            print(f"\n⚠️  Common Issues:")
            for issue in set(all_issues):
                print(f"   - {issue}")

        if all_strengths:
            print(f"\n✅ Strengths:")
            for strength in set(all_strengths):
                print(f"   - {strength}")

    # Step 4: Suggest improvements
    suggest_prompt_improvements()

    # Step 5: Test prompt variations
    await test_prompt_variations()

    print("\n🎯 Next Steps:")
    print("1. Set up API keys if not already done")
    print("2. Review and refine BAML prompts based on suggestions")
    print("3. Test with more complex project scenarios")
    print("4. Implement prompt variations and A/B test")

if __name__ == "__main__":
    asyncio.run(main())
