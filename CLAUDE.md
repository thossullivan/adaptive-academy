# Adaptive Academy Design Principles

## Core Philosophy

**Local-First, Agent-Orchestrated Learning System**

- Personal, private learning environment
- Specialized agents with clear responsibilities
- State-driven coordination between agents
- Type-safe, prompt-managed interactions

## Dual-Framework Development Strategy

To ensure a robust and reliable development process, this project employs two distinct, parallel AI agent frameworks. This separation of concerns is a foundational guardrail to reduce risk and optimize development.

### 1. The Application Crew (The "Product")

This is the user-facing agent system that delivers the learning experience.

- **Purpose**: To provide personalized education to the end-user.
- **Agents**: `CurriculumDirector`, `TutorAgent`, `AssessmentCoach`.
- **Environment**: The deployed, long-running Python/FastAPI service. It is the core product.

### 2. The Developer Crew (The "Process")

This is an internal-facing agent system used to build and maintain the application.

- **Purpose**: To automate the software development lifecycle for the `adaptive-academy` project itself.
- **Agents**: `Architect`, `Coder`, `CodeReviewer`, `QA_Tester`, `Integrator`.
- **Environment**: An on-demand, local tool run by developers to write, test, and review code. It is not part of the deployed product.

This strategy ensures that the AI used for development is completely separate from the AI delivered to users, creating a powerful and safe workflow.

## Design Principles

### 1. Agent Specialization & Autonomy

- **Single Responsibility**: Each agent has one clear domain of expertise
- **Stateful Agents**: Agents maintain their own context and memory
- **Minimal Coupling**: Agents communicate through shared state, not direct calls
- **Composable**: New agents can be added without changing existing ones

### 2. State Management First

- **Single Source of Truth**: SQLite database holds all canonical state
- **Event-Driven Updates**: State changes trigger agent notifications
- **Immutable History**: All learning events are logged for analysis
- **Context Propagation**: Shared LearningContext passed between agents

### 3. Type-Safe Prompt Engineering

- **BAML for Structure**: All agent prompts defined in BAML with schemas
- **Versioned Prompts**: Track prompt changes for reproducibility
- **Validated Outputs**: Type-safe responses prevent runtime errors
- **Testable Prompts**: BAML allows isolated testing of agent behaviors

### 4. Progressive Enhancement

- **MVP First**: Start simple, add complexity incrementally
- **Feature Flags**: New capabilities can be toggled on/off
- **Backward Compatibility**: Changes don't break existing workflows
- **Data Migration**: Schema changes include migration scripts

### 5. Observable & Debuggable

- **Event Logging**: All agent actions logged with context
- **State Inspection**: Current system state always visible
- **Performance Metrics**: Track learning progress and system health
- **Error Recovery**: Graceful handling of failures with rollback

## Architecture Patterns

### Agent Communication Pattern

```typescript
// Shared context object - single source of truth
interface LearningContext {
  sessionId: string;
  userId: string;
  currentModule: Module;
  learningGoals: Goal[];
  performanceData: PerformanceMetrics;
  agentStates: Record<AgentType, AgentState>;
  eventHistory: LearningEvent[];
}

// Agents receive context, return actions
interface Agent {
  processContext(context: LearningContext): Promise<AgentAction[]>;
  updateState(event: LearningEvent): void;
}
```

### State Update Flow

```
Trigger Event → Update Context → Notify Agents → Collect Actions → Execute Actions → Update State
```

### BAML Integration Pattern

```baml
// Shared schemas across all agents
class LearningContext { ... }
class AgentAction { ... }

// Agent-specific functions with shared context
function CurriculumDirector_GeneratePlan(context: LearningContext) -> CurriculumPlan
function TutorAgent_ExplainConcept(context: LearningContext, concept: string) -> Explanation
function AssessmentCoach_CreateQuiz(context: LearningContext, topic: string) -> Quiz
```

## Quality Standards

### Code Quality

- **TypeScript First**: All application code in TypeScript
- **BAML Schemas**: All LLM interactions through BAML
- **Test Coverage**: Unit tests for core logic, integration tests for workflows
- **Documentation**: README + inline comments for complex logic

### Data Quality

- **Schema Validation**: All data conforms to defined schemas
- **Audit Trail**: Complete history of learning activities
- **Backup Strategy**: Regular SQLite database backups
- **Data Privacy**: All data stays local, no external services

### User Experience

- **Fast Feedback**: Agent responses within 2-3 seconds
- **Clear Progress**: Always show current status and next steps
- **Error Messages**: Helpful, actionable error descriptions
- **Consistent Interface**: Same patterns across all interactions

## Technology Constraints

### Dependencies

- **Core**: TypeScript, BAML, SQLite, n8n
- **LLM**: Claude API (with fallback options)
- **UI**: CLI first, web interface later
- **Deployment**: Local development, self-hosted production
- **Future**: Python agents for specialized ML tasks (via JSON interface)

### Performance Targets

- **Agent Response**: < 3 seconds for typical operations
- **Database Queries**: < 100ms for state lookups
- **Memory Usage**: < 512MB for typical session
- **Storage Growth**: < 1MB per learning session

## Security & Privacy

### Data Protection

- **Local Storage**: All learning data stays on local machine
- **No Telemetry**: No usage data sent to external services
- **API Keys**: Secure storage of LLM provider credentials
- **Access Control**: File system permissions protect data

### Error Handling

- **Graceful Degradation**: System works with reduced functionality if agents fail
- **State Consistency**: Failed operations don't corrupt learning state
- **Recovery Procedures**: Clear steps to recover from common failures
- **Logging**: Sufficient detail for debugging without exposing sensitive data

## Development Guidelines

### Git Workflow

- **Feature Branches**: One branch per agent or major feature
- **Commit Messages**: Clear, descriptive commit messages
- **Code Reviews**: All changes reviewed before merge
- **Testing**: Tests pass before merge

### Agent Development

- **BAML First**: Define prompts before implementing agent logic
- **State Isolation**: Agents only modify their own state directly
- **Error Boundaries**: Each agent handles its own failures
- **Performance**: Profile and optimize slow agent operations

### Documentation

- **API Documentation**: All public interfaces documented
- **Setup Guide**: Clear instructions for new development setup
- **User Guide**: How to use the system for learning
- **Troubleshooting**: Common issues and solutions

## Success Metrics

### Learning Effectiveness

- **Module Completion Rate**: % of started modules completed
- **Knowledge Retention**: Quiz scores over time
- **Learning Velocity**: Time to complete modules vs. estimates
- **User Satisfaction**: Self-reported learning experience

### System Reliability

- **Uptime**: % of time system is available
- **Error Rate**: Failed operations per session
- **Response Time**: Agent response latency distribution
- **Data Integrity**: Zero data loss or corruption events

### Development Velocity

- **Feature Delivery**: New capabilities delivered on schedule
- **Bug Resolution**: Time from report to fix
- **Test Coverage**: % of code covered by tests
- **Technical Debt**: Manageable complexity and maintainability
