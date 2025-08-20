#!/usr/bin/env python3
"""
BAML Prompt Analysis Tool
Analyzes and demonstrates the refined BAML prompts for better structured responses.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple


def extract_baml_functions(file_path: str) -> List[Dict[str, str]]:
    """Extract BAML functions and their prompts from a schema file."""
    functions = []

    try:
        with open(file_path, 'r') as f:
            content = f.read()

        # Pattern to match BAML functions
        function_pattern = r'function\s+(\w+)\s*\((.*?)\)\s*->\s*(.*?)\s*{(.*?)}'
        matches = re.findall(function_pattern, content, re.DOTALL)

        for match in matches:
            name, params, return_type, body = match

            # Extract prompt from body
            prompt_pattern = r'prompt\s+#"(.*?)"#'
            prompt_match = re.search(prompt_pattern, body, re.DOTALL)
            prompt = prompt_match.group(1) if prompt_match else "No prompt found"

            # Extract client
            client_pattern = r'client\s+(\w+)'
            client_match = re.search(client_pattern, body)
            client = client_match.group(1) if client_match else "Unknown"

            functions.append({
                'name': name,
                'parameters': params.strip(),
                'return_type': return_type.strip(),
                'client': client,
                'prompt': prompt.strip()
            })

    except Exception as e:
        print(f"Error reading file {file_path}: {e}")

    return functions


def analyze_prompt_quality(prompt: str) -> Dict[str, any]:
    """Analyze the quality and structure of a BAML prompt."""
    analysis = {
        'length': len(prompt),
        'structure_score': 0,
        'clarity_score': 0,
        'completeness_score': 0,
        'improvements': []
    }

    # Structure analysis
    structure_indicators = [
        ('numbered_lists', r'\d+\.'),
        ('bullet_points', r'[•\-\*]'),
        ('clear_sections', r'Consider:|Provide:|Include:|Ensure:'),
        ('examples', r'[Ee]xample|[Ff]or instance'),
        ('formatting_instructions', r'format|structure|organize')
    ]

    structure_count = 0
    for indicator_name, pattern in structure_indicators:
        if re.search(pattern, prompt):
            structure_count += 1

    analysis['structure_score'] = min(structure_count * 20, 100)

    # Clarity analysis
    clarity_indicators = [
        'clear', 'specific', 'detailed', 'comprehensive',
        'step-by-step', 'systematic', 'well-defined'
    ]
    clarity_count = sum(1 for word in clarity_indicators if word.lower() in prompt.lower())
    analysis['clarity_score'] = min(clarity_count * 15, 100)

    # Completeness analysis
    completeness_indicators = [
        'context', 'requirements', 'constraints', 'assumptions',
        'deliverables', 'criteria', 'objectives', 'scope'
    ]
    completeness_count = sum(1 for word in completeness_indicators if word.lower() in prompt.lower())
    analysis['completeness_score'] = min(completeness_count * 12, 100)

    # Suggest improvements
    if analysis['structure_score'] < 60:
        analysis['improvements'].append("Add more structure with numbered lists or bullet points")

    if analysis['clarity_score'] < 60:
        analysis['improvements'].append("Include more specific clarity keywords and instructions")

    if analysis['completeness_score'] < 60:
        analysis['improvements'].append("Add more context about requirements and constraints")

    if len(prompt) < 200:
        analysis['improvements'].append("Consider expanding prompt with more detailed instructions")

    if 'example' not in prompt.lower():
        analysis['improvements'].append("Consider adding examples to clarify expectations")

    return analysis


def display_function_analysis(func: Dict[str, str]) -> None:
    """Display detailed analysis of a BAML function."""
    print(f"\n{'='*60}")
    print(f"🔧 Function: {func['name']}")
    print(f"{'='*60}")

    print(f"📥 Parameters: {func['parameters']}")
    print(f"📤 Returns: {func['return_type']}")
    print(f"🤖 Client: {func['client']}")

    print(f"\n📝 Prompt Analysis:")
    analysis = analyze_prompt_quality(func['prompt'])

    print(f"   Length: {analysis['length']} characters")
    print(f"   Structure Score: {analysis['structure_score']}/100")
    print(f"   Clarity Score: {analysis['clarity_score']}/100")
    print(f"   Completeness Score: {analysis['completeness_score']}/100")

    avg_score = (analysis['structure_score'] + analysis['clarity_score'] + analysis['completeness_score']) / 3
    print(f"   📊 Overall Quality: {avg_score:.1f}/100")

    if analysis['improvements']:
        print(f"\n💡 Suggested Improvements:")
        for improvement in analysis['improvements']:
            print(f"   • {improvement}")

    print(f"\n📄 Current Prompt:")
    print("-" * 40)
    # Show first 500 characters of prompt
    prompt_preview = func['prompt'][:500] + "..." if len(func['prompt']) > 500 else func['prompt']
    print(prompt_preview)


def show_prompt_improvements() -> None:
    """Show examples of prompt improvements for better BAML responses."""

    print("\n🎯 KEY PROMPT IMPROVEMENT STRATEGIES")
    print("="*60)

    improvements = [
        {
            "strategy": "Structured Output Requirements",
            "description": "Clearly specify the expected structure and format",
            "example": """
BEFORE:
Generate a project plan for this task.

AFTER:
Create a comprehensive project plan that includes:
1. Clear project summary (1-2 sentences)
2. Technology stack selection with justification
3. Phase breakdown (3-8 phases, each 1-6 hours)
4. Specific deliverables for each phase
5. Risk assessment and mitigation strategies
            """
        },
        {
            "strategy": "Context Enrichment",
            "description": "Provide rich context about the project and environment",
            "example": """
BEFORE:
Analyze project complexity.

AFTER:
Analyze the complexity of this software development project considering:
- Technical complexity: technology stack interactions, custom vs off-the-shelf
- Integration complexity: APIs, databases, auth systems, cross-platform needs
- Deployment complexity: infrastructure, CI/CD, scaling considerations
- Maintenance complexity: code maintainability, update frequency, monitoring
            """
        },
        {
            "strategy": "Specific Quality Criteria",
            "description": "Define what makes a good response",
            "example": """
BEFORE:
Create good acceptance criteria.

AFTER:
Create acceptance criteria that are:
- Testable and measurable
- Specific and unambiguous
- Priority-ranked (1-5 scale)
- Realistic and achievable
- Aligned with business objectives
            """
        },
        {
            "strategy": "Response Validation",
            "description": "Include self-checking mechanisms in prompts",
            "example": """
AFTER (Addition):
Before finalizing your response, verify:
1. All required fields are populated
2. Effort estimates are realistic (1-6 hours per phase)
3. Dependencies are clearly identified
4. Risk levels are appropriately assessed
5. Deliverables have measurable acceptance criteria
            """
        }
    ]

    for improvement in improvements:
        print(f"\n🔍 {improvement['strategy']}")
        print(f"📋 {improvement['description']}")
        print(f"💡 Example:")
        print(improvement['example'])


def analyze_current_baml_schema():
    """Analyze the current BAML schema for prompt quality."""

    print("🧪 BAML Prompt Quality Analysis")
    print("="*60)

    schema_file = "baml_src/learning_schemas.baml"

    if not Path(schema_file).exists():
        print(f"❌ Schema file not found: {schema_file}")
        return

    functions = extract_baml_functions(schema_file)

    if not functions:
        print("❌ No BAML functions found in schema")
        return

    print(f"✅ Found {len(functions)} BAML functions")

    # Focus on project management functions
    project_functions = [f for f in functions if 'Project' in f['name'] or 'Generate' in f['name']]

    if not project_functions:
        print("❌ No project management functions found")
        return

    print(f"\n📊 Analyzing {len(project_functions)} Project Management Functions:")

    total_score = 0
    for func in project_functions:
        display_function_analysis(func)
        analysis = analyze_prompt_quality(func['prompt'])
        avg_score = (analysis['structure_score'] + analysis['clarity_score'] + analysis['completeness_score']) / 3
        total_score += avg_score

    overall_average = total_score / len(project_functions)
    print(f"\n🎯 OVERALL ANALYSIS")
    print("="*60)
    print(f"📊 Average Prompt Quality: {overall_average:.1f}/100")

    if overall_average >= 80:
        print("🎉 Excellent! Your prompts are well-structured for reliable BAML responses.")
    elif overall_average >= 60:
        print("✅ Good! Minor improvements could enhance response consistency.")
    else:
        print("⚠️  Consider refining prompts for better structured outputs.")


def main():
    """Main function to run the analysis."""

    print("🔍 BAML Prompt Analysis & Improvement Tool")
    print("="*60)
    print("This tool analyzes BAML prompts and suggests improvements")
    print("for more reliable structured responses.\n")

    # Show general improvement strategies
    show_prompt_improvements()

    # Analyze current schema if available
    print("\n" + "="*60)
    analyze_current_baml_schema()

    print("\n🚀 RECOMMENDATIONS FOR BAML SUCCESS")
    print("="*60)

    recommendations = [
        "Use specific, structured instructions in prompts",
        "Include context about project requirements and constraints",
        "Specify output format and validation criteria clearly",
        "Add examples where helpful for complex structures",
        "Test prompts with edge cases and refine based on results",
        "Use appropriate temperature settings (0.3 for structured output)",
        "Implement fallback mechanisms for when BAML parsing fails",
        "Validate BAML responses before using in application logic"
    ]

    for i, rec in enumerate(recommendations, 1):
        print(f"{i:2d}. {rec}")

    print(f"\n💡 Next Steps:")
    print("   • Test refined prompts with your API keys")
    print("   • Monitor response consistency and adjust as needed")
    print("   • Consider A/B testing different prompt variations")
    print("   • Document successful prompt patterns for reuse")


if __name__ == "__main__":
    main()
