# Adaptive Academy - Personal MVP

## Core Architecture: A Hybrid Approach

This project uses a hybrid, microservice-based architecture to combine the strengths of a modern web framework with a powerful AI agent orchestration framework.

- **Next.js / TypeScript Frontend**: The user-facing application, responsible for all UI, user interaction, and client-side state management.
- **Python / Autogen Backend**: A separate service that hosts and orchestrates the AI agents. It handles all complex business logic and communication with the LLM.
- **BAML (Boundary AI Markup Language)**: The shared, typed layer that defines the interface to the LLM. It acts as a contract, ensuring that the data passed between the frontend, backend, and the LLM is always structured and predictable.

This separation of concerns allows us to use the best tools for each task, creating a scalable and maintainable system.

---

## The Agent Team

### Core Agents (MVP)

1.  **Curriculum Director** - Master planning and sequencing of learning topics.
2.  **Tutor Agent** - Interactive teaching, explanations, and answering questions.
3.  **Assessment Coach** - Quizzing, progress evaluation, and identifying weak areas.

**Phase 2 Agents (Future):**

- **Implementation Guide** - Code reviews and project guidance.
- **Research Assistant** - Paper recommendations and summaries.
- **Progress Tracker** - Analytics and adaptation.

## The Tech Stack

- **BAML**: The contract for generating structured, typed outputs from the LLM.
- **FastAPI**: The web framework for the Python agent service.
- **Autogen**: The framework for orchestrating AI agent conversations.
- **Obsidian**: Knowledge base and note-taking.
- **SQLite**: Local progress tracking for the MVP.
- **GitHub**: Code repositories and version control.

## BAML Integration Strategy: The AI Contract

BAML is the single source of truth for all LLM interactions. It provides end-to-end type safety between the Python backend and the TypeScript frontend.

1.  **Define in BAML**: Create functions and schemas in `.baml` files.
2.  **Generate Code**: Run `baml build` to generate typed clients for both Python and TypeScript.
3.  **Orchestrate in Python**: The Autogen agents use the Python BAML client to call LLM functions as tools. These functions return Pydantic objects that match the BAML schema.
4.  **Consume in TypeScript**: The Next.js frontend uses the generated TypeScript types to safely handle data from the Python API.

### Key BAML Use Cases

**Curriculum Director:**

```baml
function GenerateCurriculum(topic: string, user_profile: LearningProfile) -> Curriculum {
  client GPT4
  prompt #"
    Generate a structured learning curriculum for {{topic}}.

    User Profile:
    - Background: {{user_profile.background}}
    - Time Commitment: {{user_profile.hours_per_day}} hours/day
    - Learning Style: {{user_profile.learning_style}}

    Return a curriculum with clear modules, timelines, and prerequisites.
  "#
}
```

**Assessment Coach:**

```baml
function CreateQuiz(topic: string, difficulty: int, question_count: int) -> Quiz {
  client GPT4
  prompt #"
    Create {{question_count}} quiz questions for {{topic}} at difficulty level {{difficulty}}/10.

    Include:
    - Multiple choice questions
    - Conceptual understanding questions
    - Practical application problems

    Format as structured quiz with explanations.
  "#
}
```

## Agent Orchestration (Autogen)

The Python backend uses Microsoft's Autogen to manage the conversational logic between agents. This replaces the need for a separate workflow tool like n8n.

### Core Conversation Flow

1.  A user action in the Next.js app triggers an API call to the Python/FastAPI server.
2.  The API endpoint initiates an Autogen `GroupChat` between the relevant agents (e.g., `UserProxyAgent`, `CurriculumDirector`, `TutorAgent`).
3.  Agents converse and use their registered tools (which are powered by BAML functions) to perform tasks like generating curriculum or creating quizzes.
4.  The results of the conversation are streamed back to the Next.js frontend in real-time using WebSockets.

This approach creates a dynamic and flexible learning experience that can adapt to the user's needs.

## Data Models (SQLite)

The initial database will be a local SQLite file, managed by the Python service.

```sql
-- User profile and preferences
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY,
    background TEXT,
    hours_per_day REAL,
    learning_style TEXT,
    current_focus TEXT
);

-- Learning curriculum and progress
CREATE TABLE curriculum (
    id INTEGER PRIMARY KEY,
    topic TEXT,
    module_name TEXT,
    prerequisites TEXT,
    estimated_hours REAL,
    status TEXT -- 'not_started', 'in_progress', 'completed'
);

-- Assessment results and performance
CREATE TABLE assessments (
    id INTEGER PRIMARY KEY,
    module_id INTEGER,
    quiz_score REAL,
    completion_time INTEGER,
    weak_areas TEXT,
    timestamp DATETIME,
    FOREIGN KEY (module_id) REFERENCES curriculum (id)
);
```

## Implementation Plan

### Phase 1: Foundation & Backend Setup

1.  **Scaffold Python Service**: Create a new `agent_service` directory with a FastAPI application.
2.  **Basic Agent**: Implement a single Autogen agent (e.g., `TutorAgent`) with a basic system message.
3.  **BAML Integration**: Create one BAML function (e.g., `ExplainConcept`) and generate the Python client.
4.  **API Endpoint**: Create a FastAPI endpoint that takes a user prompt and initiates a simple agent conversation.
5.  **Frontend-Backend Communication**: Establish API communication between the Next.js app and the new Python service. Implement a basic WebSocket connection for real-time updates.

### Phase 2: Core MVP Agent Implementation

1.  **Implement All Agents**: Create Autogen versions of the `CurriculumDirector` and `AssessmentCoach`.
2.  **Tool Integration**: Wrap all BAML functions as tools and register them with the appropriate agents.
3.  **Database Access**: Connect the Python service to the SQLite database, with database operations exposed as tools for the agents.
4.  **End-to-End Flow**: Build a complete, end-to-end learning module workflow orchestrated by Autogen.

### Phase 3: Polish & Documentation

1.  **Error Handling**: Implement robust error handling and logging in both services.
2.  **Configuration Management**: Centralize configuration for both Next.js and Python services.
3.  **Testing**: Write unit and integration tests for the agent service.
4.  **Documentation**: Fully document the new architecture, API endpoints, and agent capabilities.

## Future Considerations & Enhancements

### Features to Add Post-MVP

- **Multi-topic curriculum generation**
- **Learning style detection and adaptation**
- **Advanced analytics and progress tracking**
- **Integration of `ResearchAssistant` and `ImplementationGuide` agents**
- **Complex conversational flows using Autogen's `GroupChatManager`**

### Technical Scaling

- **PostgreSQL Migration**: The system is designed for a future migration from SQLite to PostgreSQL when scaling is required. The database logic is abstracted to facilitate this.
- **Asynchronous Tool Execution**: For long-running agent tools, explore and implement asynchronous execution patterns.
- **Containerization**: Dockerize the Next.js and Python services for simplified deployment and scaling.
- **Cloud Deployment**: Plan for deploying the services to a cloud provider.
