"""Main CLI for the Developer Crew using modern AutoGen API."""

import os
import asyncio
import typer
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from dotenv import load_dotenv

from .agents import CoderAgent, CodeReviewerAgent, QA_TesterAgent, ProjectManagerAgent
from .model_clients import ModelClientFactory, get_default_model
from .baml_project_manager_simple import SimpleBAMLProjectManager

# Load environment variables
load_dotenv()

app = typer.Typer(name="dev-crew", help="AI Developer Crew for automating software development tasks")
console = Console()


def check_api_key() -> bool:
    """Check if any supported API key is configured."""
    status = ModelClientFactory.validate_setup()

    if not status["available_models"]:
        missing_deps = "\n".join([f"  pip install {dep}" for dep in status["missing_dependencies"]])
        missing_keys = "\n".join([f"  export {key}='your-key-here'" for key in status["missing_api_keys"]])

        error_msg = "❌ No API keys found for supported providers.\n\n"

        if missing_deps:
            error_msg += f"Missing dependencies:\n{missing_deps}\n\n"

        if missing_keys:
            error_msg += f"Missing API keys:\n{missing_keys}\n\n"

        error_msg += "Supported providers: Anthropic (Claude), OpenAI (GPT), Google (Gemini)"

        console.print(Panel(
            Text(error_msg, style="red"),
            title="API Configuration Required",
            border_style="red"
        ))
        return False

    # Show available models
    console.print(Panel(
        Text(f"✅ Found {len(status['available_models'])} available models:\n" +
             "\n".join([f"  • {model}" for model in status['available_models']]),
             style="green"),
        title="API Configuration",
        border_style="green"
    ))
    return True


@app.command("code")
def code_task(
    prompt: str = typer.Argument(..., help="Task description for the Coder agent"),
    model: str = typer.Option(None, help="Model to use (supports OpenAI, Anthropic, Google - auto-detects from available APIs)"),
    working_dir: str = typer.Option(".", help="Working directory for the task")
):
    """Execute a coding task using the Coder agent."""

    if not check_api_key():
        raise typer.Exit(1)

    # Use default model if none specified
    if model is None:
        model = get_default_model()
        if model is None:
            console.print("❌ No supported model available. Please configure an API key.")
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
                api_key=os.getenv("ANTHROPIC_API_KEY")
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
    path: str = typer.Argument(".", help="Path to code to review"),
    model: str = typer.Option(None, help="Model to use (supports OpenAI, Anthropic, Google - auto-detects from available APIs)"),
    output_file: str = typer.Option("", help="Optional file to save review results")
):
    """Review code quality using the CodeReviewer agent."""

    if not check_api_key():
        raise typer.Exit(1)

    # Use default model if none specified
    if model is None:
        model = get_default_model()
        if model is None:
            console.print("❌ No supported model available. Please configure an API key.")
            raise typer.Exit(1)

    console.print(Panel(
        f"👁️ Initializing Code Reviewer Agent\n"
        f"📄 Path: {path}\n"
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
                model=model
            )

            # Run the review
            result = await reviewer.review(path)

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


@app.command("test")
def test_code(
    target: str = typer.Argument(..., help="File, directory, or functionality to test"),
    working_dir: str = typer.Option(".", help="Working directory for tests"),
    model: str = typer.Option(None, help="Model to use (supports OpenAI, Anthropic, Google - auto-detects from available APIs)"),
):
    """Test and validate code using the QA Tester agent."""

    if not check_api_key():
        raise typer.Exit(1)

    # Use default model if none specified
    if model is None:
        model = get_default_model()
        if model is None:
            console.print("❌ No supported model available. Please configure an API key.")
            raise typer.Exit(1)

    console.print(Panel(
        f"🧪 Initializing QA Tester Agent\n"
        f"🎯 Target: {target}\n"
        f"📁 Working Directory: {working_dir}\n"
        f"🔧 Model: {model}",
        title="Developer Crew - QA Testing",
        border_style="yellow"
    ))

    async def run_qa_tests():
        tester = None

        try:
            # Initialize the QA Tester agent
            console.print("🔍 Starting code testing and validation...")

            tester = QA_TesterAgent(
                model=model,
                api_key=os.getenv("ANTHROPIC_API_KEY")
            )

            # Run the tests
            result = await tester.test(target, working_dir)

            console.print(Panel(
                result,
                title="✅ Testing Completed",
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
            if tester:
                await tester.close()

    # Run the async task
    asyncio.run(run_qa_tests())


@app.command("workflow")
def run_workflow(
    task: str = typer.Argument(..., help="Development task to complete"),
    working_dir: str = typer.Option(".", help="Working directory for the task"),
    model: str = typer.Option(None, help="Model to use (supports OpenAI, Anthropic, Google - auto-detects from available APIs)"),
    skip_review: bool = typer.Option(False, help="Skip code review step"),
    skip_testing: bool = typer.Option(False, help="Skip testing step"),
):
    """Run the complete development workflow: Code -> Review -> Test."""

    if not check_api_key():
        raise typer.Exit(1)

    # Use default model if none specified
    if model is None:
        model = get_default_model()
        if model is None:
            console.print("❌ No supported model available. Please configure an API key.")
            raise typer.Exit(1)

    console.print(Panel(
        f"⚙️ Starting Development Workflow\n"
        f"📝 Task: {task}\n"
        f"📁 Working Directory: {working_dir}\n"
        f"🔧 Model: {model}\n"
        f"⏭️ Skip Review: {skip_review}\n"
        f"⏭️ Skip Testing: {skip_testing}",
        title="Developer Crew - Full Workflow",
        border_style="blue"
    ))

    async def run_development_workflow():
        # Change to working directory
        original_dir = os.getcwd()
        coder = None
        reviewer = None
        tester = None

        try:
            if working_dir != ".":
                os.chdir(working_dir)
                console.print(f"📂 Changed to directory: {os.getcwd()}")

            workflow_results = {
                "coding": None,
                "review": None,
                "testing": None
            }

            # Phase 1: Code Generation
            console.print("\n" + "="*50)
            console.print("🤖 Phase 1: Code Generation")
            console.print("="*50)

            coder = CoderAgent(model=model)

            coding_result = await coder.run(task)
            workflow_results["coding"] = coding_result

            console.print(Panel(
                coding_result,
                title="✅ Phase 1 Complete: Code Generation",
                border_style="green"
            ))

            # Phase 2: Code Review (if not skipped)
            if not skip_review:
                console.print("\n" + "="*50)
                console.print("👁️ Phase 2: Code Review")
                console.print("="*50)

                reviewer = CodeReviewerAgent(model=model)

                # Extract created files from coding result
                created_files = []
                if "Successfully wrote to" in coding_result:
                    # Extract filenames from the coding result
                    lines = coding_result.split('\n')
                    for line in lines:
                        if "Successfully wrote to" in line and ":" in line:
                            # Extract filename from "Successfully wrote to filename.ext:"
                            parts = line.split("Successfully wrote to ")[1].split(":")[0].strip()
                            if parts:
                                created_files.append(parts)

                # Review each created file or fallback to current directory
                if created_files:
                    review_results = []
                    for file_path in created_files:
                        try:
                            file_review = await reviewer.review(file_path)
                            review_results.append(f"## Review of {file_path}\n{file_review}")
                        except Exception as e:
                            review_results.append(f"## Review of {file_path}\n❌ Error reviewing file: {str(e)}")

                    review_result = "\n\n".join(review_results)
                else:
                    # Fallback: create a general review task
                    review_task = f"""Please review the code that was just generated for the following task:

Original task: {task}

Generated code output:
{coding_result}

Please analyze the project structure, find any newly created files, and provide a comprehensive code review."""

                    try:
                        response = await reviewer.agent.run(task=review_task)
                        # Use the same parsing logic as in the agent
                        if hasattr(response, 'messages') and response.messages:
                            for message in reversed(response.messages):
                                if hasattr(message, 'content') and message.content:
                                    if hasattr(message, 'type') and message.type not in ['ThoughtEvent', 'ToolCallRequestEvent', 'ToolCallExecutionEvent']:
                                        review_result = message.content
                                        break
                                    elif not hasattr(message, 'type'):
                                        review_result = message.content
                                        break
                            else:
                                review_result = "Review completed - please check the generated files manually."
                        else:
                            review_result = "Review completed - please check the generated files manually."
                    except Exception as e:
                        review_result = f"❌ Error during code review: {str(e)}"

                workflow_results["review"] = review_result

                console.print(Panel(
                    review_result,
                    title="✅ Phase 2 Complete: Code Review",
                    border_style="yellow"
                ))
            else:
                console.print("⏭️ Skipping code review phase")

            # Phase 3: Testing (if not skipped)
            if not skip_testing:
                console.print("\n" + "="*50)
                console.print("🧪 Phase 3: Testing & Validation")
                console.print("="*50)

                tester = QA_TesterAgent(model=model)

                # Test the current directory or specific files
                test_target = f"Code generated for task: {task}. Please test all Python files in the current directory."
                testing_result = await tester.test(test_target, working_dir)
                workflow_results["testing"] = testing_result

                console.print(Panel(
                    testing_result,
                    title="✅ Phase 3 Complete: Testing & Validation",
                    border_style="green"
                ))
            else:
                console.print("⏭️ Skipping testing phase")

            # Final Summary
            console.print("\n" + "="*60)
            console.print("📋 WORKFLOW SUMMARY")
            console.print("="*60)

            summary = f"""
✅ **Code Generation**: Completed
   Task: {task}

{'✅' if not skip_review else '⏭️'} **Code Review**: {'Completed' if not skip_review else 'Skipped'}

{'✅' if not skip_testing else '⏭️'} **Testing**: {'Completed' if not skip_testing else 'Skipped'}

**Next Steps:**
- Review the generated code and make any necessary adjustments
- Run additional tests if needed
- Deploy or integrate the code as appropriate
"""

            console.print(Panel(
                summary,
                title="🎉 Development Workflow Complete",
                border_style="green"
            ))

        except Exception as e:
            console.print(Panel(
                f"❌ Workflow Error: {str(e)}",
                title="Error",
                border_style="red"
            ))
            raise typer.Exit(1)

        finally:
            # Clean up all agents
            if coder:
                await coder.close()
            if reviewer:
                await reviewer.close()
            if tester:
                await tester.close()

            # Restore original directory
            os.chdir(original_dir)

    # Run the async workflow
    asyncio.run(run_development_workflow())


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


@app.command("plan")
def plan_project(
    task: str = typer.Argument(..., help="Complex development task to create a plan for"),
    working_dir: str = typer.Option(".", help="Working directory to analyze for context"),
    model: str = typer.Option(None, help="Model to use (supports OpenAI, Anthropic, Google - auto-detects from available APIs)"),
    output_file: str = typer.Option("", help="Optional file to save the project plan")
):
    """Create a comprehensive project plan for complex development tasks."""

    if not check_api_key():
        raise typer.Exit(1)

    # Use default model if none specified
    if model is None:
        model = get_default_model()
        if model is None:
            console.print("❌ No supported model available. Please configure an API key.")
            raise typer.Exit(1)

    console.print(Panel(
        f"📋 Initializing Project Manager Agent\n"
        f"📝 Task: {task}\n"
        f"📁 Working Directory: {working_dir}\n"
        f"🔧 Model: {model}",
        title="Developer Crew - Project Planning",
        border_style="cyan"
    ))

    async def create_project_plan():
        pm = None

        try:
            console.print("🔍 Analyzing project and creating comprehensive plan...")

            pm = ProjectManagerAgent(model=model)

            # Create the project plan
            plan = await pm.create_project_plan(task, working_dir)

            if "error" in plan:
                console.print(Panel(
                    plan["error"],
                    title="❌ Error Creating Project Plan",
                    border_style="red"
                ))
                return

            # Display the plan
            plan_display = f"📋 **PROJECT**: {plan.get('project_summary', 'Complex Development Task')}\n\n"

            if plan.get('technology_stack'):
                plan_display += f"🛠️ **TECH STACK**: {', '.join(plan['technology_stack'])}\n\n"

            plan_display += "📅 **EXECUTION PHASES**:\n\n"

            for i, phase in enumerate(plan.get('phases', []), 1):
                plan_display += f"**Phase {phase.get('phase_number', i)}: {phase.get('phase_name', f'Phase {i}')}**\n"
                plan_display += f"└ {phase.get('description', 'No description')}\n"

                if phase.get('deliverables'):
                    plan_display += f"├ Deliverables: {', '.join(phase['deliverables'])}\n"

                if phase.get('estimated_effort'):
                    plan_display += f"├ Effort: {phase['estimated_effort']}\n"

                if phase.get('git_strategy'):
                    plan_display += f"├ Git: {phase['git_strategy']}\n"

                if phase.get('potential_risks'):
                    plan_display += f"└ Risks: {', '.join(phase['potential_risks'])}\n"

                plan_display += "\n"

            if plan.get('integration_plan'):
                plan_display += f"🔗 **INTEGRATION**: {plan['integration_plan']}\n\n"

            if plan.get('deployment_considerations'):
                plan_display += f"🚀 **DEPLOYMENT**: {plan['deployment_considerations']}"

            console.print(Panel(
                plan_display,
                title="✅ Project Plan Created",
                border_style="green"
            ))

            # Save to file if requested
            if output_file:
                import json
                try:
                    with open(output_file, 'w') as f:
                        json.dump(plan, f, indent=2)
                    console.print(f"📄 Plan saved to: {output_file}")
                except Exception as e:
                    console.print(f"❌ Error saving plan: {str(e)}")

            # Show next steps
            console.print(Panel(
                "🎯 **NEXT STEPS**:\n"
                "1. Review the project plan and adjust if needed\n"
                "2. Use `workflow` command to execute individual phases\n"
                "3. Consider using git branches for each phase\n"
                "4. Execute phases in order, with review and testing\n\n"
                f"💡 **TIP**: Execute Phase 1 with:\n"
                f"`uv run python -m developer_crew.main workflow \"Phase 1: {plan.get('phases', [{}])[0].get('phase_name', 'Setup')}\" --working-dir {working_dir}`",
                title="Project Planning Complete",
                border_style="blue"
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
            if pm:
                await pm.close()

    # Run the async task
    asyncio.run(create_project_plan())


@app.command("plan-baml")
def plan_project_baml(
    task: str = typer.Argument(..., help="Development task to create a BAML-powered plan for"),
    working_dir: str = typer.Option(".", help="Working directory to analyze for context"),
    output_file: str = typer.Option("", help="Optional file to save the project plan")
):
    """Create a project plan using BAML structured outputs (EXPERIMENTAL)."""

    if not check_api_key():
        raise typer.Exit(1)

    console.print(Panel(
        f"🧪 Initializing BAML Project Manager (EXPERIMENTAL)\n"
        f"📝 Task: {task}\n"
        f"📁 Working Directory: {working_dir}",
        title="Developer Crew - BAML Project Planning",
        border_style="cyan"
    ))

    async def create_baml_project_plan():
        pm = None

        try:
            console.print("🔍 Analyzing project with BAML structured outputs...")

            pm = SimpleBAMLProjectManager()

            # Create the project plan using BAML
            plan = await pm.create_project_plan(task, working_dir)

            if plan.get("error"):
                console.print(Panel(
                    f"⚠️ BAML Error (using fallback): {plan['error']}",
                    title="BAML Integration Warning",
                    border_style="yellow"
                ))

            # Display the plan
            plan_display = f"📋 **PROJECT**: {plan.get('project_summary', 'Development Task')}\n\n"

            if plan.get('technology_stack'):
                plan_display += f"🛠️ **TECH STACK**: {', '.join(plan['technology_stack'])}\n\n"

            plan_display += "📅 **EXECUTION PHASES**:\n\n"

            for phase in plan.get('phases', []):
                plan_display += f"**Phase {phase.get('phase_number', 1)}: {phase.get('phase_name', 'Unnamed Phase')}**\n"
                plan_display += f"└ {phase.get('description', 'No description')}\n"

                if phase.get('deliverables'):
                    deliverable_names = [d.get('name', d) if isinstance(d, dict) else d for d in phase['deliverables']]
                    plan_display += f"├ Deliverables: {', '.join(deliverable_names)}\n"

                if phase.get('estimated_effort'):
                    plan_display += f"├ Effort: {phase['estimated_effort']}\n"

                if phase.get('git_strategy'):
                    plan_display += f"├ Git: {phase['git_strategy']}\n"

                plan_display += "\n"

            plan_display += f"⚡ **TOTAL EFFORT**: {plan.get('total_estimated_effort', 'Unknown')}\n"
            plan_display += f"🎯 **SUCCESS METRICS**: {', '.join(plan.get('success_metrics', ['Project completion']))}\n"
            plan_display += f"🔧 **BAML POWERED**: {'✅ Yes' if plan.get('baml_powered') else '❌ Fallback used'}"

            console.print(Panel(
                plan_display,
                title="✅ BAML Project Plan Created",
                border_style="green"
            ))

            # Save to file if requested
            if output_file:
                import json
                try:
                    with open(output_file, 'w') as f:
                        json.dump(plan, f, indent=2)
                    console.print(f"📄 BAML plan saved to: {output_file}")
                except Exception as e:
                    console.print(f"❌ Error saving plan: {str(e)}")

            # Show next steps
            console.print(Panel(
                "🎯 **BAML INTEGRATION STATUS**:\n"
                f"• Structured outputs: {'✅ Working' if plan.get('baml_powered') else '❌ Failed, used fallback'}\n"
                f"• Type safety: {'✅ Enabled' if plan.get('baml_powered') else '⚠️ Limited'}\n"
                f"• Validation: {'✅ Automatic' if plan.get('baml_powered') else '⚠️ Manual'}\n\n"
                "💡 **NEXT STEPS**:\n"
                "1. Compare with regular `plan` command output\n"
                "2. Use `workflow` command to execute phases\n"
                "3. Report any BAML integration issues\n\n"
                f"🚀 **EXECUTE FIRST PHASE**:\n"
                f"`uv run python -m developer_crew.main workflow \"Phase 1\" --working-dir {working_dir}`",
                title="BAML Integration Test Complete",
                border_style="blue"
            ))

        except Exception as e:
            console.print(Panel(
                f"❌ BAML Test Error: {str(e)}",
                title="BAML Integration Error",
                border_style="red"
            ))
            raise typer.Exit(1)

        finally:
            # Clean up
            if pm:
                await pm.close()

    # Run the async task
    asyncio.run(create_baml_project_plan())


@app.command("setup-test")
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
        from .agents import CoderAgent, CodeReviewerAgent, QA_TesterAgent
        from .tools import read_file, write_file
        console.print("✅ All imports successful")
    except ImportError as e:
        console.print(f"❌ Import error: {e}")
        raise typer.Exit(1)

    # Test basic functionality
    async def test_agent_creation():
        try:
            # Test agent creation
            coder = CoderAgent(api_key=os.getenv("ANTHROPIC_API_KEY"))
            reviewer = CodeReviewerAgent(api_key=os.getenv("ANTHROPIC_API_KEY"))
            tester = QA_TesterAgent(api_key=os.getenv("ANTHROPIC_API_KEY"))

            console.print("✅ Agent creation successful")

            # Clean up
            await coder.close()
            await reviewer.close()
            await tester.close()

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
