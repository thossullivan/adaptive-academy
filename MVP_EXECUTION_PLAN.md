# MVP Execution Plan: A Two-Part Strategy

## Overview

This document outlines a two-part strategy to build the Adaptive Academy project. The core idea is to first build the tools, then use those tools to build the product.

1.  **Part 1: Build the AI Developer Crew.** We will first create an internal, AI-powered team of agents designed to automate our software development lifecycle. This is a reusable asset that acts as a force multiplier.
2.  **Part 2: Build the Adaptive Academy Application.** With the Developer Crew operational, we will then use it to build, test, and deploy the user-facing learning application.

This approach is designed to maximize development velocity, ensure high code quality through automated reviews and testing, and create a scalable development process.

---

## Part 1: Build the AI Developer Crew

### Overview

This phase focuses on creating our "AI factory"—a command-line tool that orchestrates a team of specialized AI agents to perform software engineering tasks.

### Phase 1: Foundation & The `Coder` Agent

**Goal:** Create a single, functional agent that can write and modify code based on a precise instruction.

- [ ] Create a new Python project directory: `developer_crew`.
- [ ] Set up a `pyproject.toml` and a virtual environment.
- [ ] Install core dependencies: `pyautogen`, `python-dotenv`, `typer`.
- [ ] Implement the `Coder` agent with a focused system prompt.
- [ ] Implement file system tools (`read_file`, `edit_file`) for the agent.
- [ ] Create a simple CLI (`main.py`) to pass a prompt to the `Coder`.

**Phase 1 Deliverable:** A command-line tool that successfully uses a single `Coder` agent to write a specified file.

### Phase 2: Adding Guardrails - The `Reviewer` and `Tester`

**Goal:** Establish a quality control process by adding static and dynamic analysis agents.

- [ ] Implement the `CodeReviewer` agent with a system prompt focused on static analysis. It should only have a `read_file` tool.
- [ ] Implement the `QA_Tester` agent with a system prompt focused on code execution and validation. It should have the `terminal` tool.
- [ ] Create an orchestration script for the workflow: `Coder` writes -> `CodeReviewer` approves -> `QA_Tester` approves.

**Phase 2 Deliverable:** A three-agent script that can write, review, and test a simple Python script, correctly identifying bugs and style issues.

### Phase 3: Full Crew Orchestration

**Goal:** Build a fully autonomous, conversational development team that can manage a feedback loop.

- [ ] Implement the `Architect` agent for high-level planning.
- [ ] Implement the `Integrator` agent to act as the `GroupChatManager`, mediating the conversation.
- [ ] Set up an Autogen `GroupChat` containing all agents.
- [ ] Implement the full conversational workflow with feedback loops (e.g., `Reviewer` sends notes back to `Coder`).
- [ ] Configure a `UserProxyAgent` with `human_input_mode="ALWAYS"` to require final human approval.

**Phase 3 Deliverable:** A fully orchestrated agent crew that can take a high-level request, plan it, code it, test it, and present the final code for human approval.

### Phase 4: Polish & First Real Task

**Goal:** Refine the Developer Crew into a reusable tool and use it to build the foundation of the `adaptive-academy` application.

- [ ] Refine all agent system prompts based on performance in prior phases.
- [ ] Package the crew into a clean, reusable command-line interface.
- [ ] **First Task:** Use the newly built Developer Crew to execute the prompt: _"Scaffold a new FastAPI application in a directory named `agent_service`. It should have a health check endpoint at `/api/health`. Include a `README.md` and a `.gitignore` file."_

**Phase 4 Deliverable:** A polished, reusable AI developer tool and the initial, AI-generated project structure for the `adaptive-academy` application.

---

## Part 2: Build the Adaptive Academy Application

### Overview

With the Developer Crew operational, we will now build the user-facing application. The Developer Crew will be used to execute the tasks in this plan, turning high-level goals into production code.

### Phase 1: Foundation & Backend Setup

**Goal:** Create the core backend service and establish communication with the frontend.

- [ ] **Task for Dev Crew:** "Scaffold the FastAPI service." (Completed in Part 1, Phase 4).
- [ ] **Task for Dev Crew:** "Implement a single Autogen agent, the `TutorAgent`, with a basic system message. Create a basic API endpoint that takes a user prompt and initiates a conversation with this agent."
- [ ] **Task for Dev Crew:** "Integrate BAML into the project. Create a single BAML function `ExplainConcept` and generate the Python client."
- [ ] **Task for Dev Crew:** "Establish a WebSocket endpoint for streaming agent messages back to a client."

**Phase 1 Deliverable:** A running FastAPI service that can host a single Autogen agent, with BAML integrated and real-time communication established.

### Phase 2: Core MVP Agent Implementation

**Goal:** Implement the full team of application agents and their primary tools.

- [ ] **Task for Dev Crew:** "Implement Autogen versions of the `CurriculumDirector` and `AssessmentCoach` agents."
- [ ] **Task for Dev Crew:** "Create BAML functions for `GenerateCurriculum` and `CreateQuiz`."
- [ ] **Task for Dev Crew:** "Wrap all BAML functions as tools and register them with the appropriate agents."
- [ ] **Task for Dev Crew:** "Connect the Python service to a SQLite database. Create tools for the agents to read and write to the database."

**Phase 2 Deliverable:** The three core application agents are fully implemented and can use BAML and SQLite as tools.

### Phase 3: End-to-End Learning Flow

**Goal:** Create a complete, user-driven learning experience from start to finish.

- [ ] **Task for Dev Crew:** "Orchestrate the full agent `GroupChat` for the Application Crew."
- [ ] **Task for Dev Crew:** "Build the API endpoints required to manage a full learning session: start, get status, send message, end."
- [ ] **Task for Dev Crew:** "Work with the Next.js frontend team to integrate these API endpoints to display the agent conversation."

**Phase 3 Deliverable:** A user can start a session in the Next.js UI and have a complete, interactive learning conversation with the backend agents.

### Phase 4: Polish, Testing, and Documentation

**Goal:** Harden the application and prepare it for MVP release.

- [ ] **Task for Dev Crew:** "Implement robust error handling and structured logging across the Python service."
- [ ] **Task for Dev Crew:** "Write unit and integration tests for the core agent interactions and API endpoints."
- [ ] **Task for Dev Crew:** "Generate comprehensive API documentation."

**Phase 4 Deliverable:** A production-ready, tested, and documented MVP of the Adaptive Academy application.
