"""AI agents for the developer crew using modern AutoGen API with multi-provider support."""

import asyncio
import json
import re
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, ChatMessage
from autogen_agentchat.base import Response

from .model_clients import ModelClientFactory, get_default_model
from .tools import (
    read_file, write_file, edit_file, list_files, get_project_structure,
    execute_command, run_python_script, run_tests, check_code_quality
)


class CoderAgent:
    """AI agent specialized in writing and modifying code using modern AutoGen API. """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize the Coder agent.

        Args:
            model: Model to use (e.g., 'claude-3-5-sonnet-20241022', 'gpt-4', 'gemini-pro')
                  If not provided, will use the best available model
            api_key: API key for the model provider (if not provided, will use environment variables)
        """
        # Use default model if none specified
        if model is None:
            model = get_default_model()
            if model is None:
                raise ValueError(
                    "No API keys found. Please set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"
                )

        self.model = model
        self.model_client = ModelClientFactory.create_client(model, api_key)

        system_message = """You are an expert full-stack software developer with deep expertise in modern web technologies. Your role is to write, modify, and improve code based on precise instructions.

Core Responsibilities:
- Write clean, well-structured, and maintainable code
- Follow established patterns and conventions in existing codebases
- Implement features according to specifications
- Fix bugs and improve code quality
- Add appropriate comments and documentation

Backend Expertise:
- Python (FastAPI, Django, Flask), Node.js, databases (SQLite, PostgreSQL)
- RESTful APIs, GraphQL, WebSocket implementations
- Authentication, authorization, and security best practices

Frontend Expertise:
- React 18+, Next.js 14+ (App Router), TypeScript, modern JavaScript (ES2022+)
- Component patterns: composition, compound components, render props, custom hooks
- State management: React Context, Zustand, React Query/TanStack Query
- Styling: Tailwind CSS, CSS Modules, styled-components
- UI Libraries: shadcn/ui, Radix UI, Headless UI
- Performance: Code splitting, lazy loading, React.memo, useMemo, useCallback
- Accessibility: ARIA labels, semantic HTML, keyboard navigation
- Testing: Jest, React Testing Library, Playwright, Vitest

Modern Development Practices:
- TypeScript best practices: strict mode, proper typing, generic constraints
- Code organization: barrel exports, folder structure, separation of concerns
- Error boundaries, loading states, optimistic updates
- Progressive enhancement, responsive design
- Bundle optimization, tree shaking, performance monitoring

Guidelines:
1. Always read existing files before modifying to understand context and patterns
2. Follow the existing code style and conventions
3. Write code that is readable, maintainable, and follows best practices
4. Test your understanding by summarizing what you're going to implement before coding
5. Use appropriate data structures and algorithms for the task
6. Handle errors gracefully with proper TypeScript error types
7. When creating new files, include proper imports and structure
8. For React components: use TypeScript interfaces, proper prop validation, and accessibility
9. For Next.js: leverage App Router patterns, server components when appropriate
10. For API integration: implement proper error handling, loading states, and type safety

Available Tools:
- read_file: Read the contents of a file
- write_file: Write content to a new file
- edit_file: Modify existing file by replacing content
- list_files: List files in a directory
- get_project_structure: Get an overview of project structure

Always use these tools to interact with the filesystem. Never attempt to write code without first understanding the existing codebase structure and patterns.

When you need to use a tool, describe what you're going to do first, then use the tool, then explain the results and next steps."""

        # Create tools first
        self.tools = self._create_tools()

        self.agent = AssistantAgent(
            name="Coder",
            model_client=self.model_client,
            system_message=system_message,
            tools=self.tools,
        )

    def _create_tools(self):
        """Create file system tools for the agent."""

        def read_file_tool(file_path: str) -> str:
            """Read a file and return its contents."""
            result = read_file(file_path)
            if result["success"]:
                return f"Successfully read {file_path}:\n\n{result['content']}"
            else:
                return f"Error reading {file_path}: {result['error']}"

        def write_file_tool(file_path: str, content: str) -> str:
            """Write content to a file."""
            result = write_file(file_path, content)
            if result["success"]:
                return f"Successfully wrote to {file_path}: {result['message']}"
            else:
                return f"Error writing to {file_path}: {result['error']}"

        def edit_file_tool(file_path: str, old_content: str, new_content: str) -> str:
            """Edit a file by replacing old_content with new_content."""
            result = edit_file(file_path, old_content, new_content)
            if result["success"]:
                return f"Successfully edited {file_path}: {result['message']}"
            else:
                return f"Error editing {file_path}: {result['error']}"

        def list_files_tool(directory_path: str, pattern: str = "*") -> str:
            """List files in a directory."""
            result = list_files(directory_path, pattern)
            if result["success"]:
                files_list = "\n".join(f"  - {f}" for f in result['files'])
                return f"Files in {directory_path}:\n{files_list}"
            else:
                return f"Error listing files in {directory_path}: {result['error']}"

        def get_project_structure_tool(root_path: str = ".", max_depth: int = 3) -> str:
            """Get an overview of the project structure."""
            result = get_project_structure(root_path, max_depth)
            if result["success"]:
                structure_str = "Project structure:\n"
                for path, items in result["structure"].items():
                    structure_str += f"\n{path}:\n"
                    for item in items:
                        structure_str += f"  {item}\n"
                return structure_str
            else:
                return f"Error analyzing project structure: {result['error']}"

        # Return list of tools
        return [read_file_tool, write_file_tool, edit_file_tool, list_files_tool, get_project_structure_tool]

    async def run(self, task: str) -> str:
        """Run a coding task.

        Args:
            task: Description of the coding task to perform

        Returns:
            The agent's response as a string
        """
        try:
            response = await self.agent.run(task=task)

            # Try different response formats from AutoGen
            if hasattr(response, 'messages') and response.messages:
                # Look for the last meaningful message that's not an event
                for message in reversed(response.messages):
                    if hasattr(message, 'content') and message.content:
                        # Skip system/thought events, look for actual responses
                        if hasattr(message, 'type') and message.type not in ['ThoughtEvent', 'ToolCallRequestEvent', 'ToolCallExecutionEvent']:
                            return message.content
                        elif not hasattr(message, 'type'):
                            return message.content

                # If no good message found, summarize the actions taken
                actions = []
                for message in response.messages:
                    if hasattr(message, 'type') and message.type == 'ToolCallExecutionEvent':
                        if hasattr(message, 'content') and message.content:
                            for result in message.content:
                                if hasattr(result, 'content'):
                                    actions.append(f"✅ {result.content}")

                if actions:
                    return "Code generation completed successfully!\n\n" + "\n".join(actions[-3:])  # Show last 3 actions

            elif hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                # Extract content from the last message
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content

            return "Task completed successfully!"
        except Exception as e:
            return f"Error executing task: {str(e)}"

    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()


class CodeReviewerAgent:
    """AI agent specialized in reviewing code quality and suggesting improvements."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize the Code Reviewer agent.

        Args:
            model: Model to use (e.g., 'claude-3-5-sonnet-20241022', 'gpt-4', 'gemini-pro')
                  If not provided, will use the best available model
            api_key: API key for the model provider (if not provided, will use environment variables)
        """
        # Use default model if none specified
        if model is None:
            model = get_default_model()
            if model is None:
                raise ValueError(
                    "No API keys found. Please set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"
                )

        self.model = model
        self.model_client = ModelClientFactory.create_client(model, api_key)

        system_message = """You are an expert code reviewer with deep knowledge of software engineering best practices. Your role is to review code for quality, correctness, and maintainability.

Core Responsibilities:
- Review code for bugs, logic errors, and potential issues
- Check adherence to coding standards and best practices
- Suggest improvements for performance, readability, and maintainability
- Verify proper error handling and edge case coverage
- Ensure code follows security best practices
- Check for proper documentation and comments

Review Criteria:
1. Correctness: Does the code do what it's supposed to do?
2. Performance: Are there any performance issues or inefficiencies?
3. Security: Are there any security vulnerabilities?
4. Maintainability: Is the code easy to understand and modify?
5. Style: Does the code follow established conventions?
6. Testing: Is the code testable and well-structured?
7. Documentation: Are complex parts properly documented?

Output Format:
- Start with an overall assessment (APPROVED, NEEDS_CHANGES, or REJECTED)
- List specific issues found with line numbers if applicable
- Provide concrete suggestions for improvement
- Highlight positive aspects of the code

Available Tools:
- read_file: Read and analyze file contents
- list_files: Explore project structure
- get_project_structure: Understand overall project layout

Focus on providing constructive, actionable feedback that helps improve code quality."""

        # Create tools first
        self.tools = self._create_review_tools()

        self.agent = AssistantAgent(
            name="CodeReviewer",
            model_client=self.model_client,
            system_message=system_message,
            tools=self.tools,
        )

    def _create_review_tools(self):
        """Create read-only tools for code review."""

        def read_file_tool(file_path: str) -> str:
            """Read a file and return its contents."""
            result = read_file(file_path)
            if result["success"]:
                return f"Content of {file_path}:\n\n{result['content']}"
            else:
                return f"Error reading {file_path}: {result['error']}"

        def list_files_tool(directory_path: str, pattern: str = "*") -> str:
            """List files in a directory."""
            result = list_files(directory_path, pattern)
            if result["success"]:
                files_list = "\n".join(f"  - {f}" for f in result['files'])
                return f"Files in {directory_path}:\n{files_list}"
            else:
                return f"Error listing files in {directory_path}: {result['error']}"

        def get_project_structure_tool(root_path: str = ".", max_depth: int = 3) -> str:
            """Get an overview of the project structure."""
            result = get_project_structure(root_path, max_depth)
            if result["success"]:
                structure_str = "Project structure:\n"
                for path, items in result["structure"].items():
                    structure_str += f"\n{path}:\n"
                    for item in items:
                        structure_str += f"  {item}\n"
                return structure_str
            else:
                return f"Error analyzing project structure: {result['error']}"

        # Return list of read-only tools
        return [read_file_tool, list_files_tool, get_project_structure_tool]

    async def review(self, file_path: str) -> str:
        """Review a specific file.

        Args:
            file_path: Path to the file to review

        Returns:
            The review results as a string
        """
        task = f"""Please review the code in file: {file_path}

Provide a thorough code review including:
1. Overall assessment (APPROVED, NEEDS_CHANGES, or REJECTED)
2. Specific issues found (with line numbers if applicable)
3. Suggestions for improvement
4. Positive aspects of the code
5. Security considerations
6. Performance implications

Start by reading the file, then provide your detailed review."""

        try:
            response = await self.agent.run(task=task)

            # Try different response formats from AutoGen
            if hasattr(response, 'messages') and response.messages:
                # Look for the last meaningful message that's not an event
                for message in reversed(response.messages):
                    if hasattr(message, 'content') and message.content:
                        # Skip system/thought events, look for actual responses
                        if hasattr(message, 'type') and message.type not in ['ThoughtEvent', 'ToolCallRequestEvent', 'ToolCallExecutionEvent']:
                            return message.content
                        elif not hasattr(message, 'type'):
                            return message.content

                # If no good message found, summarize the actions taken
                actions = []
                for message in response.messages:
                    if hasattr(message, 'type') and message.type == 'ToolCallExecutionEvent':
                        if hasattr(message, 'content') and message.content:
                            for result in message.content:
                                if hasattr(result, 'content'):
                                    actions.append(f"✅ {result.content}")

                if actions:
                    return "Code review completed successfully!\n\n" + "\n".join(actions[-3:])  # Show last 3 actions

            elif hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                # Extract content from the last message
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content

            return "Review completed successfully!"
        except Exception as e:
            return f"Error during code review: {str(e)}"

    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()


class QA_TesterAgent:
    """AI agent specialized in testing and validating code through execution."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize the QA Tester agent.

        Args:
            model: Model to use (e.g., 'claude-3-5-sonnet-20241022', 'gpt-4', 'gemini-pro')
                  If not provided, will use the best available model
            api_key: API key for the model provider (if not provided, will use environment variables)
        """
        # Use default model if none specified
        if model is None:
            model = get_default_model()
            if model is None:
                raise ValueError(
                    "No API keys found. Please set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"
                )

        self.model = model
        self.model_client = ModelClientFactory.create_client(model, api_key)

        system_message = """You are an expert QA engineer and testing specialist. Your role is to validate code through execution, testing, and dynamic analysis.

Core Responsibilities:
- Execute code to verify it works as intended
- Run automated tests and interpret results
- Identify runtime errors, performance issues, and edge cases
- Validate that code meets functional requirements
- Check code quality through static analysis tools
- Provide detailed test reports and recommendations

Testing Approach:
1. **Static Analysis First**: Run code quality tools (ruff, mypy) to catch obvious issues
2. **Syntax Validation**: Ensure Python files can be parsed and imported
3. **Unit Testing**: Run existing tests and verify they pass
4. **Functional Testing**: Execute code with sample inputs to verify behavior
5. **Edge Case Testing**: Test boundary conditions and error handling
6. **Performance Check**: Look for obvious performance issues

Available Tools:
- execute_command: Run shell commands safely
- run_python_script: Execute Python scripts with arguments
- run_tests: Run test suites using pytest, unittest, or nose
- check_code_quality: Run static analysis tools (ruff, mypy, black, flake8)
- read_file: Read files to understand test requirements
- list_files: Explore project structure for test files

Testing Workflow:
1. Read and understand the code being tested
2. Check for existing test files
3. Run static analysis tools first
4. Execute any existing tests
5. If no tests exist, create simple test cases to validate functionality
6. Report findings with specific recommendations

Output Format:
- Start with overall test status (PASS, FAIL, or PARTIAL)
- List all tests executed and their results
- Report any errors, warnings, or issues found
- Provide specific recommendations for fixes
- Include code quality metrics when available

Security Note: Only execute safe, approved commands. Never run commands that could harm the system."""

        # Create tools first
        self.tools = self._create_testing_tools()

        self.agent = AssistantAgent(
            name="QA_Tester",
            model_client=self.model_client,
            system_message=system_message,
            tools=self.tools,
        )

    def _create_testing_tools(self):
        """Create testing and execution tools for the agent."""

        def execute_command_tool(
            command: str,
            working_dir: Optional[str] = None,
            timeout: int = 30
        ) -> str:
            """Execute a shell command safely."""
            result = execute_command(command, working_dir, timeout)

            output = f"Command: {result['command']}\n"
            output += f"Return Code: {result['return_code']}\n"
            output += f"Working Directory: {result.get('working_dir', 'N/A')}\n"

            if result["success"]:
                output += f"✅ SUCCESS\nOutput:\n{result['stdout']}"
                if result["stderr"]:
                    output += f"\nWarnings/Info:\n{result['stderr']}"
            else:
                output += f"❌ FAILED\nError:\n{result['stderr']}"
                if result["stdout"]:
                    output += f"\nOutput:\n{result['stdout']}"

            return output

        def run_python_script_tool(
            script_path: str,
            args: Optional[str] = None,
            working_dir: Optional[str] = None,
            timeout: int = 30
        ) -> str:
            """Run a Python script with optional arguments."""
            args_list = args.split() if args else None
            result = run_python_script(script_path, args_list, working_dir, timeout)

            output = f"Python Script: {script_path}\n"
            if args:
                output += f"Arguments: {args}\n"
            output += f"Return Code: {result['return_code']}\n"

            if result["success"]:
                output += f"✅ SUCCESS\nOutput:\n{result['stdout']}"
            else:
                output += f"❌ FAILED\nError:\n{result['stderr']}"
                if result["stdout"]:
                    output += f"\nOutput:\n{result['stdout']}"

            return output

        def run_tests_tool(
            test_path: Optional[str] = None,
            test_framework: str = "pytest",
            working_dir: Optional[str] = None,
            timeout: int = 120
        ) -> str:
            """Run tests using specified framework."""
            result = run_tests(test_path, test_framework, working_dir, timeout)

            output = f"Test Framework: {test_framework}\n"
            output += f"Test Path: {test_path or 'auto-detect'}\n"
            output += f"Return Code: {result['return_code']}\n"

            if result["success"]:
                output += f"✅ TESTS PASSED\nOutput:\n{result['stdout']}"
            else:
                output += f"❌ TESTS FAILED\nError:\n{result['stderr']}"
                if result["stdout"]:
                    output += f"\nOutput:\n{result['stdout']}"

            return output

        def check_code_quality_tool(
            file_or_dir: str,
            tools: Optional[str] = None,
            working_dir: Optional[str] = None,
            timeout: int = 60
        ) -> str:
            """Run code quality checks."""
            tools_list = tools.split(",") if tools else None
            if tools_list:
                tools_list = [t.strip() for t in tools_list]

            result = check_code_quality(file_or_dir, tools_list, working_dir, timeout)

            output = f"Code Quality Check: {file_or_dir}\n"
            output += f"Tools: {', '.join(result.get('summary', []))}\n"
            output += f"Overall Status: {'✅ PASSED' if result['overall_success'] else '❌ FAILED'}\n\n"

            for tool, tool_result in result.get('tool_results', {}).items():
                output += f"\n--- {tool.upper()} ---\n"
                if tool_result.get("success"):
                    output += "✅ PASSED\n"
                    if tool_result.get("stdout"):
                        output += f"Output: {tool_result['stdout']}\n"
                else:
                    output += "❌ FAILED\n"
                    if tool_result.get("error"):
                        output += f"Error: {tool_result['error']}\n"
                    if tool_result.get("stderr"):
                        output += f"Issues: {tool_result['stderr']}\n"

            return output

        def read_file_tool(file_path: str) -> str:
            """Read a file to understand test requirements."""
            result = read_file(file_path)
            if result["success"]:
                return f"Content of {file_path}:\n\n{result['content']}"
            else:
                return f"Error reading {file_path}: {result['error']}"

        def list_files_tool(directory_path: str, pattern: str = "*") -> str:
            """List files to find tests and code to analyze."""
            result = list_files(directory_path, pattern)
            if result["success"]:
                files_list = "\n".join(f"  - {f}" for f in result['files'])
                return f"Files in {directory_path}:\n{files_list}"
            else:
                return f"Error listing files in {directory_path}: {result['error']}"

        # Return list of all tools
        return [
            execute_command_tool,
            run_python_script_tool,
            run_tests_tool,
            check_code_quality_tool,
            read_file_tool,
            list_files_tool
        ]

    async def test(self, target: str, working_dir: Optional[str] = None) -> str:
        """Test a file, directory, or specific functionality.

        Args:
            target: File, directory, or description of what to test
            working_dir: Directory to run tests in

        Returns:
            The test results and recommendations
        """
        task = f"""Please test and validate: {target}

Follow this testing workflow:

1. **Static Analysis**: Run code quality checks first (ruff, mypy)
2. **Explore Structure**: List files to understand the project layout
3. **Run Existing Tests**: Look for and run any existing test files
4. **Functional Validation**: If it's a Python file, try to import/execute it safely
5. **Create Test Report**: Provide detailed results and recommendations

Working Directory: {working_dir or 'current directory'}

Provide a comprehensive test report with:
- Overall test status (PASS/FAIL/PARTIAL)
- Results from each testing phase
- Any errors or issues discovered
- Specific recommendations for improvements
- Code quality metrics

Start by analyzing what type of testing is most appropriate for the target."""

        try:
            response = await self.agent.run(task=task)

            # Try different response formats from AutoGen
            if hasattr(response, 'messages') and response.messages:
                # Look for the last meaningful message that's not an event
                for message in reversed(response.messages):
                    if hasattr(message, 'content') and message.content:
                        # Skip system/thought events, look for actual responses
                        if hasattr(message, 'type') and message.type not in ['ThoughtEvent', 'ToolCallRequestEvent', 'ToolCallExecutionEvent']:
                            return message.content
                        elif not hasattr(message, 'type'):
                            return message.content

                # If no good message found, summarize the actions taken
                actions = []
                for message in response.messages:
                    if hasattr(message, 'type') and message.type == 'ToolCallExecutionEvent':
                        if hasattr(message, 'content') and message.content:
                            for result in message.content:
                                if hasattr(result, 'content'):
                                    actions.append(f"✅ {result.content}")

                if actions:
                    return "Testing completed successfully!\n\n" + "\n".join(actions[-3:])  # Show last 3 actions

            elif hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content

            return "Testing completed successfully!"
        except Exception as e:
            return f"Error during testing: {str(e)}"

    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()


class ProjectManagerAgent:
    """AI agent specialized in project planning and task orchestration for complex development tasks."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """Initialize the Project Manager agent.

        Args:
            model: Model to use (e.g., 'claude-3-5-sonnet-20241022', 'gpt-4', 'gemini-pro')
                  If not provided, will use the best available model
            api_key: API key for the model provider (if not provided, will use environment variables)
        """
        # Use default model if none specified
        if model is None:
            model = get_default_model()
            if model is None:
                raise ValueError(
                    "No API keys found. Please set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"
                )

        self.model = model
        self.model_client = ModelClientFactory.create_client(model, api_key)

        system_message = """You are an expert Project Manager and Software Architect with deep expertise in breaking down complex software development tasks into manageable, executable phases.

Core Responsibilities:
- Analyze complex development requirements and create detailed project plans
- Break large tasks into logical phases with clear deliverables
- Define technical architecture and technology stack decisions
- Create implementation order that minimizes dependencies and risks
- Estimate effort and identify potential blockers
- Plan Git workflow with appropriate branching strategy

Project Planning Expertise:
- Requirements analysis and user story creation
- Technical architecture design (frontend, backend, database, APIs)
- Dependency mapping and critical path analysis
- Risk assessment and mitigation strategies
- Quality gates and acceptance criteria definition
- DevOps and deployment planning

Output Format:
Always structure your project plans as JSON with this schema:
{
  "project_summary": "Brief description of the overall project",
  "technology_stack": ["list", "of", "technologies"],
  "phases": [
    {
      "phase_number": 1,
      "phase_name": "Setup & Foundation",
      "description": "What this phase accomplishes",
      "deliverables": ["specific", "files", "or", "features"],
      "estimated_effort": "1-2 hours",
      "dependencies": [],
      "git_strategy": "create feature branch, commit after review",
      "acceptance_criteria": ["criterion 1", "criterion 2"],
      "potential_risks": ["risk 1", "risk 2"]
    }
  ],
  "integration_plan": "How phases come together",
  "deployment_considerations": "Production readiness steps"
}

Always think step-by-step and consider:
1. What are the core requirements?
2. What's the minimal viable first step?
3. How can I minimize dependencies between phases?
4. What could go wrong and how do I mitigate it?
5. How will this be tested and deployed?

CRITICAL: You MUST respond with valid JSON wrapped in ```json code blocks. Example:

```json
{
  "project_summary": "Your project description here",
  "technology_stack": ["Next.js", "TypeScript", "Tailwind"],
  "phases": [
    {
      "phase_number": 1,
      "phase_name": "Project Setup",
      "description": "Initialize project with basic structure",
      "deliverables": ["package.json", "tsconfig.json", "basic components"],
      "estimated_effort": "2-3 hours",
      "dependencies": [],
      "git_strategy": "create feature branch",
      "acceptance_criteria": ["Project builds successfully", "Basic structure in place"],
      "potential_risks": ["Version compatibility issues"]
    }
  ],
  "integration_plan": "How phases integrate together",
  "deployment_considerations": "Production deployment steps"
}
```

Always provide this JSON format in your response."""

        self.agent = AssistantAgent(
            name="ProjectManager",
            model_client=self.model_client,
            system_message=system_message,
            tools=self._create_planning_tools()
        )

    def _create_planning_tools(self) -> List:
        """Create tools for project planning and analysis."""

        def analyze_project_structure_tool(root_path: str = ".", max_depth: int = 3) -> str:
            """Analyze existing project structure for planning purposes."""
            result = get_project_structure(root_path, max_depth)
            if result["success"]:
                structure_str = "Existing Project Structure Analysis:\n"
                for path, items in result["structure"].items():
                    structure_str += f"\n{path}:\n"
                    for item in items:
                        structure_str += f"  {item}\n"
                return structure_str
            else:
                return f"Error analyzing project structure: {result['error']}"

        def read_existing_files_tool(file_path: str) -> str:
            """Read existing project files to understand current state."""
            result = read_file(file_path)
            if result["success"]:
                return f"Content of {file_path}:\n\n{result['content']}"
            else:
                return f"Error reading {file_path}: {result['error']}"

        def list_project_files_tool(directory_path: str, pattern: str = "*") -> str:
            """List files in project directory for analysis."""
            result = list_files(directory_path, pattern)
            if result["success"]:
                files_list = "\n".join(f"  - {f}" for f in result['files'])
                return f"Files in {directory_path} matching '{pattern}':\n{files_list}"
            else:
                return f"Error listing files in {directory_path}: {result['error']}"

        return [analyze_project_structure_tool, read_existing_files_tool, list_project_files_tool]

    async def create_project_plan(self, task: str, working_dir: str = ".") -> Dict[str, Any]:
        """Create a comprehensive project plan for a complex development task.

        Args:
            task: Description of the complex development task
            working_dir: Working directory to analyze for existing project context

        Returns:
            Dictionary containing the structured project plan
        """
        planning_prompt = f"""Please create a comprehensive project plan for the following development task:

TASK: {task}

WORKING DIRECTORY: {working_dir}

Please analyze the existing project structure first, then create a detailed project plan following the JSON schema provided in your system message.

Key considerations:
1. Start by understanding what already exists in the project
2. Break the task into 3-8 logical phases (not too many, not too few)
3. Each phase should have clear, testable deliverables
4. Minimize dependencies between phases where possible
5. Consider Git workflow - each phase should be committable
6. Include specific file names and features where appropriate
7. Estimate effort realistically
8. Identify potential risks and blockers

Make sure the plan is actionable and that each phase can be executed by a single developer in a reasonable time (1-4 hours per phase)."""

        try:
            response = await self.agent.run(task=planning_prompt)

            # Parse response using the same logic as other agents
            content = self._parse_response(response)

            # Try to extract JSON from the response
            plan = self._extract_json_plan(content)

            if plan:
                # Validate required fields
                if not plan.get('phases'):
                    plan['phases'] = []
                if not plan.get('project_summary'):
                    plan['project_summary'] = task
                return plan
            else:
                # Enhanced fallback: try to create a better plan from the response
                phases = self._create_fallback_phases(task, content)

                return {
                    "project_summary": task,
                    "technology_stack": self._extract_technologies(content),
                    "phases": phases,
                    "integration_plan": "Phases will be executed sequentially with review and testing",
                    "deployment_considerations": "Standard deployment practices apply",
                    "raw_response": content,
                    "parsing_note": "JSON parsing failed, using intelligent fallback"
                }

        except Exception as e:
            return {
                "error": f"Error creating project plan: {str(e)}",
                "project_summary": task,
                "phases": []
            }

    def _parse_response(self, response) -> str:
        """Parse AutoGen response to extract meaningful content."""
        if hasattr(response, 'messages') and response.messages:
            # Look for the last meaningful message that's not an event
            for message in reversed(response.messages):
                if hasattr(message, 'content') and message.content:
                    if hasattr(message, 'type') and message.type not in ['ThoughtEvent', 'ToolCallRequestEvent', 'ToolCallExecutionEvent']:
                        return message.content
                    elif not hasattr(message, 'type'):
                        return message.content

            # If no good message found, summarize actions
            actions = []
            for message in response.messages:
                if hasattr(message, 'type') and message.type == 'ToolCallExecutionEvent':
                    if hasattr(message, 'content') and message.content:
                        for result in message.content:
                            if hasattr(result, 'content'):
                                actions.append(result.content)

            if actions:
                return "Project analysis completed:\n\n" + "\n\n".join(actions)

        elif hasattr(response, 'chat_message') and response.chat_message:
            return response.chat_message.content
        elif hasattr(response, 'inner_messages') and response.inner_messages:
            last_message = response.inner_messages[-1]
            if hasattr(last_message, 'content'):
                return last_message.content

        return "Project plan created successfully!"

    def _extract_json_plan(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract JSON project plan from response content."""
        try:
            # Look for JSON blocks in the content (most reliable)
            json_pattern = r'```json\s*(\{.*?\})\s*```'
            json_match = re.search(json_pattern, content, re.DOTALL)

            if json_match:
                json_str = json_match.group(1)
                return json.loads(json_str)

            # Try to find JSON without code blocks but with proper structure
            json_pattern = r'\{.*?"phases".*?\[.*?\].*?\}'
            json_match = re.search(json_pattern, content, re.DOTALL)

            if json_match:
                json_str = json_match.group(0)
                return json.loads(json_str)

            # Try to find any JSON-like structure in the content
            lines = content.split('\n')
            json_lines = []
            in_json = False
            brace_count = 0

            for line in lines:
                stripped = line.strip()
                if stripped.startswith('{'):
                    in_json = True
                    json_lines = [line]
                    brace_count = line.count('{') - line.count('}')
                elif in_json:
                    json_lines.append(line)
                    brace_count += line.count('{') - line.count('}')
                    if brace_count == 0:
                        # Try to parse the accumulated JSON
                        json_str = '\n'.join(json_lines)
                        try:
                            parsed = json.loads(json_str)
                            if 'phases' in parsed:
                                return parsed
                        except json.JSONDecodeError:
                            pass
                        in_json = False
                        json_lines = []

        except (json.JSONDecodeError, AttributeError, Exception):
            pass

        return None

    def _create_fallback_phases(self, task: str, content: str) -> List[Dict[str, Any]]:
        """Create fallback phases when JSON parsing fails."""
        # Try to identify key phases from the response content
        phases = []

        if "next.js" in content.lower() or "react" in content.lower():
            phases = [
                {
                    "phase_number": 1,
                    "phase_name": "Project Setup & Foundation",
                    "description": "Initialize Next.js project with basic structure and dependencies",
                    "deliverables": ["package.json", "next.config.js", "basic file structure"],
                    "estimated_effort": "1-2 hours",
                    "dependencies": [],
                    "git_strategy": "create feature branch",
                    "acceptance_criteria": ["Project builds and runs successfully"],
                    "potential_risks": ["Version compatibility issues"]
                },
                {
                    "phase_number": 2,
                    "phase_name": "UI Foundation",
                    "description": "Set up shadcn/ui and core components",
                    "deliverables": ["shadcn/ui components", "theme configuration", "basic layout"],
                    "estimated_effort": "2-3 hours",
                    "dependencies": ["Phase 1"],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["UI components render correctly"],
                    "potential_risks": ["Styling conflicts"]
                },
                {
                    "phase_number": 3,
                    "phase_name": "Core Features",
                    "description": "Implement main functionality based on requirements",
                    "deliverables": ["Core feature implementation"],
                    "estimated_effort": "4-6 hours",
                    "dependencies": ["Phase 2"],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["Features work as expected"],
                    "potential_risks": ["Complex business logic"]
                }
            ]
        else:
            # Generic phases for other projects
            phases = [
                {
                    "phase_number": 1,
                    "phase_name": "Analysis & Setup",
                    "description": "Analyze requirements and set up project structure",
                    "deliverables": ["Project structure", "Configuration files"],
                    "estimated_effort": "1-2 hours",
                    "dependencies": [],
                    "git_strategy": "create feature branch",
                    "acceptance_criteria": ["Project is ready for development"],
                    "potential_risks": ["Unclear requirements"]
                },
                {
                    "phase_number": 2,
                    "phase_name": "Core Implementation",
                    "description": "Implement main functionality",
                    "deliverables": ["Core feature implementation"],
                    "estimated_effort": "3-4 hours",
                    "dependencies": ["Phase 1"],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["Core features working"],
                    "potential_risks": ["Technical complexity"]
                },
                {
                    "phase_number": 3,
                    "phase_name": "Testing & Polish",
                    "description": "Add tests and polish the implementation",
                    "deliverables": ["Test suite", "Documentation", "Bug fixes"],
                    "estimated_effort": "1-2 hours",
                    "dependencies": ["Phase 2"],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["All tests pass", "Code is documented"],
                    "potential_risks": ["Test coverage gaps"]
                }
            ]

        return phases

    def _extract_technologies(self, content: str) -> List[str]:
        """Extract technology stack from response content."""
        technologies = []
        tech_keywords = {
            "next.js": "Next.js 14",
            "react": "React",
            "typescript": "TypeScript",
            "tailwind": "Tailwind CSS",
            "shadcn": "shadcn/ui",
            "python": "Python",
            "fastapi": "FastAPI",
            "django": "Django",
            "flask": "Flask",
            "postgresql": "PostgreSQL",
            "sqlite": "SQLite",
            "mongodb": "MongoDB",
            "redis": "Redis",
            "docker": "Docker",
            "node.js": "Node.js"
        }

        content_lower = content.lower()
        for keyword, tech in tech_keywords.items():
            if keyword in content_lower and tech not in technologies:
                technologies.append(tech)

        if not technologies:
            technologies = ["To be determined based on requirements"]

        return technologies

    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()
