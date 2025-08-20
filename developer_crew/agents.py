"""AI agents for the developer crew using modern AutoGen API."""

import asyncio
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.messages import TextMessage, ChatMessage
from autogen_agentchat.base import Response

from .tools import (
    read_file, write_file, edit_file, list_files, get_project_structure,
    execute_command, run_python_script, run_tests, check_code_quality
)


class CoderAgent:
    """AI agent specialized in writing and modifying code using modern AutoGen API."""
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize the Coder agent.
        
        Args:
            model: OpenAI model to use (default: gpt-4)
            api_key: OpenAI API key (if not provided, will use environment variable)
        """
        self.model_client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
        
        system_message = """You are an expert software developer and coding specialist. Your role is to write, modify, and improve code based on precise instructions.

Core Responsibilities:
- Write clean, well-structured, and maintainable code
- Follow established patterns and conventions in existing codebases
- Implement features according to specifications
- Fix bugs and improve code quality
- Add appropriate comments and documentation

Guidelines:
1. Always read existing files before modifying to understand context and patterns
2. Follow the existing code style and conventions
3. Write code that is readable, maintainable, and follows best practices
4. Test your understanding by summarizing what you're going to implement before coding
5. Use appropriate data structures and algorithms for the task
6. Handle errors gracefully and add appropriate error checking
7. When creating new files, include proper imports and structure

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
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                # Extract content from the last message
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error executing task: {str(e)}"
    
    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()


class CodeReviewerAgent:
    """AI agent specialized in reviewing code quality and suggesting improvements."""
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize the Code Reviewer agent.
        
        Args:
            model: OpenAI model to use (default: gpt-4)
            api_key: OpenAI API key (if not provided, will use environment variable)
        """
        self.model_client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
        
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
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                # Extract content from the last message
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error during code review: {str(e)}"
    
    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()


class QA_TesterAgent:
    """AI agent specialized in testing and validating code through execution."""
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize the QA Tester agent.
        
        Args:
            model: OpenAI model to use (default: gpt-4)
            api_key: OpenAI API key (if not provided, will use environment variable)
        """
        self.model_client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
        
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
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error during testing: {str(e)}"
    
    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()