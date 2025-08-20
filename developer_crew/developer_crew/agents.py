"""AI agents for the developer crew using modern AutoGen API."""

import asyncio
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.messages import TextMessage, ChatMessage
from autogen_agentchat.base import Response

from .tools import read_file, write_file, edit_file, list_files, get_project_structure


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

        self.agent = AssistantAgent(
            name="Coder",
            model_client=self.model_client,
            system_message=system_message,
        )
        
        # Register tools
        self._register_tools()
    
    def _register_tools(self):
        """Register file system tools with the agent."""
        
        async def read_file_tool(file_path: str) -> str:
            """Read a file and return its contents."""
            result = read_file(file_path)
            if result["success"]:
                return f"Successfully read {file_path}:\n\n{result['content']}"
            else:
                return f"Error reading {file_path}: {result['error']}"
        
        async def write_file_tool(file_path: str, content: str) -> str:
            """Write content to a file."""
            result = write_file(file_path, content)
            if result["success"]:
                return f"Successfully wrote to {file_path}: {result['message']}"
            else:
                return f"Error writing to {file_path}: {result['error']}"
        
        async def edit_file_tool(file_path: str, old_content: str, new_content: str) -> str:
            """Edit a file by replacing old_content with new_content."""
            result = edit_file(file_path, old_content, new_content)
            if result["success"]:
                return f"Successfully edited {file_path}: {result['message']}"
            else:
                return f"Error editing {file_path}: {result['error']}"
        
        async def list_files_tool(directory_path: str, pattern: str = "*") -> str:
            """List files in a directory."""
            result = list_files(directory_path, pattern)
            if result["success"]:
                files_list = "\n".join(f"  - {f}" for f in result['files'])
                return f"Files in {directory_path}:\n{files_list}"
            else:
                return f"Error listing files in {directory_path}: {result['error']}"
        
        async def get_project_structure_tool(root_path: str = ".", max_depth: int = 3) -> str:
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
        
        # Register tools with the agent
        self.agent.register_tool(read_file_tool)
        self.agent.register_tool(write_file_tool)
        self.agent.register_tool(edit_file_tool)
        self.agent.register_tool(list_files_tool)
        self.agent.register_tool(get_project_structure_tool)
    
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

        self.agent = AssistantAgent(
            name="CodeReviewer",
            model_client=self.model_client,
            system_message=system_message,
        )
        
        # Register read-only tools
        self._register_tools()
    
    def _register_tools(self):
        """Register read-only tools for code review."""
        
        async def read_file_tool(file_path: str) -> str:
            """Read a file and return its contents."""
            result = read_file(file_path)
            if result["success"]:
                return f"Content of {file_path}:\n\n{result['content']}"
            else:
                return f"Error reading {file_path}: {result['error']}"
        
        async def list_files_tool(directory_path: str, pattern: str = "*") -> str:
            """List files in a directory."""
            result = list_files(directory_path, pattern)
            if result["success"]:
                files_list = "\n".join(f"  - {f}" for f in result['files'])
                return f"Files in {directory_path}:\n{files_list}"
            else:
                return f"Error listing files in {directory_path}: {result['error']}"
        
        async def get_project_structure_tool(root_path: str = ".", max_depth: int = 3) -> str:
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
        
        # Register read-only tools
        self.agent.register_tool(read_file_tool)
        self.agent.register_tool(list_files_tool)
        self.agent.register_tool(get_project_structure_tool)
    
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