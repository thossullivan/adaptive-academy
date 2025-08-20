"""Main CLI for the Developer Crew using modern AutoGen API."""

import os
import asyncio
import typer
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from dotenv import load_dotenv

from .agents import CoderAgent, CodeReviewerAgent

# Load environment variables
load_dotenv()

app = typer.Typer(name="dev-crew", help="AI Developer Crew for automating software development tasks")
console = Console()


def check_api_key() -> bool:
    """Check if OpenAI API key is configured."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        console.print(Panel(
            Text("❌ OPENAI_API_KEY not found in environment variables.\n\n"
                 "Please set your OpenAI API key:\n"
                 "export OPENAI_API_KEY='your-api-key-here'\n\n"
                 "Or create a .env file with:\n"
                 "OPENAI_API_KEY=your-api-key-here", style="red"),
            title="Configuration Error",
            border_style="red"
        ))
        return False
    return True


@app.command("code")
def code_task(
    prompt: str = typer.Argument(..., help="Task description for the Coder agent"),
    model: str = typer.Option("gpt-4", help="OpenAI model to use"),
    working_dir: str = typer.Option(".", help="Working directory for the task")
):
    """Execute a coding task using the Coder agent."""
    
    if not check_api_key():
        raise typer.Exit(1)
    
    console.print(Panel(
        f"🤖 Initializing Coder Agent\n"
        f"📝 Task: {prompt}\n"
        f"🔧 Model: {model}\n"
        f"📁 Working Directory: {working_dir}",
        title="Developer Crew - Code Task",
        border_style="blue"
    ))
    
    async def run_coding_task():
        # Change to working directory
        original_dir = os.getcwd()
        coder = None
        
        try:
            if working_dir != ".":
                os.chdir(working_dir)
                console.print(f"📂 Changed to directory: {os.getcwd()}")
            
            # Initialize the Coder agent
            console.print("🚀 Starting code generation...")
            
            coder = CoderAgent(
                model=model,
                api_key=os.getenv("OPENAI_API_KEY")
            )
            
            # Run the task
            result = await coder.run(prompt)
            
            console.print(Panel(
                result,
                title="✅ Task Completed",
                border_style="green"
            ))
            
        except Exception as e:
            console.print(Panel(
                f"❌ Error: {str(e)}",
                title="Error",
                border_style="red"
            ))
            raise typer.Exit(1)
        
        finally:
            # Clean up
            if coder:
                await coder.close()
            # Restore original directory
            os.chdir(original_dir)
    
    # Run the async task
    asyncio.run(run_coding_task())


@app.command("review")
def review_code(
    file_path: str = typer.Argument(..., help="Path to the file to review"),
    model: str = typer.Option("gpt-4", help="OpenAI model to use"),
):
    """Review code quality using the CodeReviewer agent."""
    
    if not check_api_key():
        raise typer.Exit(1)
    
    console.print(Panel(
        f"👁️ Initializing Code Reviewer Agent\n"
        f"📄 File: {file_path}\n"
        f"🔧 Model: {model}",
        title="Developer Crew - Code Review",
        border_style="green"
    ))
    
    async def run_code_review():
        reviewer = None
        
        try:
            # Initialize the CodeReviewer agent
            console.print("🔍 Starting code review...")
            
            reviewer = CodeReviewerAgent(
                model=model,
                api_key=os.getenv("OPENAI_API_KEY")
            )
            
            # Run the review
            result = await reviewer.review(file_path)
            
            console.print(Panel(
                result,
                title="✅ Code Review Completed",
                border_style="green"
            ))
            
        except Exception as e:
            console.print(Panel(
                f"❌ Error: {str(e)}",
                title="Error",
                border_style="red"
            ))
            raise typer.Exit(1)
        
        finally:
            # Clean up
            if reviewer:
                await reviewer.close()
    
    # Run the async task
    asyncio.run(run_code_review())


@app.command("init")
def init_project():
    """Initialize a new project with Developer Crew configuration."""
    
    console.print(Panel(
        "🏗️ Initializing Developer Crew project configuration...",
        title="Project Initialization",
        border_style="blue"
    ))
    
    # Create .env file template if it doesn't exist
    env_file = ".env"
    if not os.path.exists(env_file):
        env_content = """# OpenAI API Configuration
OPENAI_API_KEY=your-openai-api-key-here

# Optional: Customize model settings
DEFAULT_MODEL=gpt-4
"""
        with open(env_file, "w") as f:
            f.write(env_content)
        console.print(f"📄 Created {env_file} template")
    
    # Create .gitignore if it doesn't exist
    gitignore_file = ".gitignore"
    if not os.path.exists(gitignore_file):
        gitignore_content = """.env
.env.local
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
pip-log.txt
pip-delete-this-directory.txt
.pytest_cache/
.coverage
htmlcov/
.DS_Store
"""
        with open(gitignore_file, "w") as f:
            f.write(gitignore_content)
        console.print(f"📄 Created {gitignore_file}")
    
    console.print("✅ Project initialization completed!")
    console.print(Panel(
        "Next steps:\n"
        "1. Edit .env file and add your OpenAI API key\n"
        "2. Run 'uv run dev-crew code \"your task description\"' to start coding\n"
        "3. Run 'uv run dev-crew review path/to/file.py' to review code",
        title="Getting Started",
        border_style="green"
    ))


@app.command("test")
def test_setup():
    """Test the Developer Crew setup and configuration."""
    
    console.print(Panel(
        "🧪 Testing Developer Crew setup...",
        title="Setup Test",
        border_style="blue"
    ))
    
    # Check API key
    if not check_api_key():
        raise typer.Exit(1)
    
    # Test imports
    try:
        from .agents import CoderAgent, CodeReviewerAgent
        from .tools import read_file, write_file
        console.print("✅ All imports successful")
    except ImportError as e:
        console.print(f"❌ Import error: {e}")
        raise typer.Exit(1)
    
    # Test basic functionality
    async def test_agent_creation():
        try:
            # Test agent creation
            coder = CoderAgent(api_key=os.getenv("OPENAI_API_KEY"))
            reviewer = CodeReviewerAgent(api_key=os.getenv("OPENAI_API_KEY"))
            
            console.print("✅ Agent creation successful")
            
            # Clean up
            await coder.close()
            await reviewer.close()
            
            console.print("✅ Agent cleanup successful")
            
        except Exception as e:
            console.print(f"❌ Agent test error: {e}")
            raise typer.Exit(1)
    
    # Run async test
    asyncio.run(test_agent_creation())
    
    console.print(Panel(
        "🎉 All tests passed! Developer Crew is ready to use.",
        title="Test Results",
        border_style="green"
    ))


if __name__ == "__main__":
    app()