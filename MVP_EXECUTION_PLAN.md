# MVP Execution Plan - Adaptive Academy

## Overview
Implementation plan to build a working personal learning system with 3 core agents, state management, and BAML integration. Pure TypeScript architecture with future Python agent extensibility.

## Phase 1: Foundation & State Management

### Project Setup
- [x] Initialize TypeScript project structure
- [x] Set up basic dependencies (BAML, SQLite, testing)
- [ ] Create database schema with proper indexing
- [ ] Implement LearningContext and state management core

### Core State System
- [ ] Build `StateManager` class for SQLite operations
- [ ] Implement `LearningContext` with proper TypeScript types
- [ ] Create event logging system for agent actions
- [ ] Add state validation and error handling

### BAML Foundation
- [ ] Set up BAML project structure (`baml/` directory)
- [ ] Define core schemas (LearningContext, Module, Assessment, etc.)
- [ ] Create first BAML function for curriculum generation
- [ ] Test BAML integration with Claude API

**Phase 1 Deliverable**: Working state management system with BAML integration

---

## Phase 2: Core Agents Implementation

### Curriculum Director Agent
- [ ] Implement `CurriculumDirectorAgent` class
- [ ] Create BAML prompts for curriculum generation
- [ ] Build hardcoded AI/ML learning roadmap
- [ ] Add module sequencing and prerequisite logic

### Tutor Agent
- [ ] Implement `TutorAgent` class  
- [ ] Create BAML prompts for concept explanations
- [ ] Add physics analogy generation capability
- [ ] Implement context-aware explanations

### Assessment Coach Agent
- [ ] Implement `AssessmentCoachAgent` class
- [ ] Create BAML prompts for quiz generation
- [ ] Add performance tracking and analysis
- [ ] Implement spaced repetition scheduling

**Phase 2 Deliverable**: Three working agents with BAML integration

---

## Phase 3: Integration & Orchestration

### Agent Orchestration
- [ ] Build `AgentOrchestrator` class
- [ ] Implement agent communication via shared context
- [ ] Create workflow coordination logic
- [ ] Add error handling and recovery

### n8n Workflow Setup
- [ ] Install and configure n8n locally
- [ ] Create basic daily study workflow
- [ ] Implement weekly review workflow
- [ ] Connect n8n to agent orchestrator

### CLI Interface
- [ ] Build command-line interface for user interactions
- [ ] Add commands for starting study sessions
- [ ] Implement progress viewing and module selection
- [ ] Create configuration management

**Phase 3 Deliverable**: End-to-end learning workflow with CLI interface

---

## Phase 4: Polish & Testing

### Testing & Validation
- [ ] Write unit tests for core state management
- [ ] Add integration tests for agent workflows
- [ ] Test BAML prompt reliability and outputs
- [ ] Validate database performance and integrity

### Error Handling & Logging
- [ ] Implement comprehensive error handling
- [ ] Add structured logging throughout system
- [ ] Create diagnostic commands for troubleshooting
- [ ] Add data backup and recovery procedures

### Documentation & User Testing
- [ ] Write setup and usage documentation
- [ ] Create troubleshooting guide
- [ ] Test complete learning workflow personally
- [ ] Refine based on real usage feedback

**Phase 4 Deliverable**: Production-ready MVP with documentation

---

## Detailed Implementation Specs

### Database Schema (Phase 1)
```sql
-- Core learning context
CREATE TABLE learning_sessions (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    current_module_id INTEGER,
    session_state JSON,
    FOREIGN KEY (current_module_id) REFERENCES curriculum (id)
);

-- Enhanced curriculum table
CREATE TABLE curriculum (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,
    module_name TEXT NOT NULL,
    description TEXT,
    prerequisites JSON, -- Array of module IDs
    estimated_hours REAL,
    difficulty_level INTEGER, -- 1-10
    status TEXT CHECK (status IN ('not_started', 'in_progress', 'completed')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

-- Agent state tracking
CREATE TABLE agent_states (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    agent_type TEXT NOT NULL,
    state_data JSON,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id),
    UNIQUE(session_id, agent_type)
);

-- Event logging for debugging and analytics
CREATE TABLE learning_events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    agent_type TEXT,
    event_type TEXT NOT NULL,
    event_data JSON,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id)
);

-- Enhanced assessments
CREATE TABLE assessments (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    module_id INTEGER NOT NULL,
    quiz_data JSON, -- Questions and answers
    user_responses JSON,
    score REAL,
    completion_time INTEGER, -- seconds
    weak_areas JSON, -- Array of concepts
    strengths JSON, -- Array of concepts
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id),
    FOREIGN KEY (module_id) REFERENCES curriculum (id)
);

-- User profile and preferences
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY,
    background TEXT,
    hours_per_day REAL,
    learning_style TEXT,
    current_focus TEXT,
    preferences JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Performance analytics
CREATE TABLE performance_metrics (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    module_id INTEGER,
    metric_type TEXT NOT NULL, -- 'completion_time', 'quiz_score', 'concept_mastery'
    metric_value REAL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id),
    FOREIGN KEY (module_id) REFERENCES curriculum (id)
);

-- Indexes for performance
CREATE INDEX idx_sessions_user ON learning_sessions(user_id);
CREATE INDEX idx_curriculum_status ON curriculum(status);
CREATE INDEX idx_events_session ON learning_events(session_id);
CREATE INDEX idx_assessments_module ON assessments(module_id);
CREATE INDEX idx_metrics_session_module ON performance_metrics(session_id, module_id);
```

### TypeScript Core Types (Phase 1)
```typescript
// Core learning context - passed between all agents
export interface LearningContext {
  sessionId: string
  userId: string
  currentModule?: Module
  learningGoals: LearningGoal[]
  performanceData: PerformanceMetrics
  agentStates: Record<AgentType, AgentState>
  eventHistory: LearningEvent[]
  userProfile: UserProfile
  preferences: UserPreferences
}

// Module definition
export interface Module {
  id: number
  topic: string
  moduleName: string
  description: string
  prerequisites: number[]
  estimatedHours: number
  difficultyLevel: number
  status: 'not_started' | 'in_progress' | 'completed'
}

// Agent types
export type AgentType = 'curriculum_director' | 'tutor' | 'assessment_coach'

// Base agent interface
export interface Agent {
  type: AgentType
  processContext(context: LearningContext): Promise<AgentAction[]>
  updateState(event: LearningEvent): Promise<void>
  getState(): AgentState
}

// Actions agents can take
export interface AgentAction {
  type: 'update_curriculum' | 'provide_explanation' | 'generate_quiz' | 'log_event'
  data: any
  priority: number
  agentId: string
}

// Events for logging and coordination
export interface LearningEvent {
  id: string
  sessionId: string
  agentType?: AgentType
  eventType: string
  eventData: any
  timestamp: Date
}

// Future: Interface for Python agents via JSON communication
export interface PythonAgentInterface {
  executeAgent(agentType: string, context: LearningContext): Promise<AgentAction[]>
}
```

### BAML Structure (Phase 1)
```
baml/
├── schemas/
│   ├── learning_context.baml
│   ├── curriculum.baml
│   ├── assessment.baml
│   └── explanation.baml
├── agents/
│   ├── curriculum_director/
│   │   ├── generate_curriculum.baml
│   │   ├── adapt_timeline.baml
│   │   └── validate_prerequisites.baml
│   ├── tutor/
│   │   ├── explain_concept.baml
│   │   ├── provide_analogy.baml
│   │   └── answer_question.baml
│   └── assessment_coach/
│       ├── generate_quiz.baml
│       ├── analyze_performance.baml
│       └── recommend_review.baml
└── functions/
    ├── orchestration.baml
    └── state_management.baml
```

### Agent Implementation Pattern (Phase 2)
```typescript
export class CurriculumDirectorAgent implements Agent {
  type: AgentType = 'curriculum_director'
  private state: CurriculumDirectorState
  
  async processContext(context: LearningContext): Promise<AgentAction[]> {
    const actions: AgentAction[] = []
    
    // Check if curriculum needs generation or adaptation
    if (this.shouldGenerateCurriculum(context)) {
      const curriculum = await this.generateCurriculum(context)
      actions.push({
        type: 'update_curriculum',
        data: curriculum,
        priority: 1,
        agentId: this.type
      })
    }
    
    // Check if timeline needs adjustment
    if (this.shouldAdaptTimeline(context)) {
      const adjustments = await this.adaptTimeline(context)
      actions.push({
        type: 'update_curriculum',
        data: adjustments,
        priority: 2,
        agentId: this.type
      })
    }
    
    return actions
  }
  
  private async generateCurriculum(context: LearningContext): Promise<Curriculum> {
    // BAML call to generate structured curriculum
    return await BAML.GenerateCurriculum({
      topic: context.userProfile.currentFocus,
      userProfile: context.userProfile,
      performanceHistory: context.performanceData
    })
  }
  
  // ... other methods
}
```

## Success Criteria

### Phase 1 Success
- [ ] Database schema created and validated
- [ ] LearningContext flows through state management
- [ ] First BAML function returns structured output
- [ ] Basic error handling and logging works

### Phase 2 Success  
- [ ] All three agents respond to context changes
- [ ] BAML prompts generate realistic curricula/quizzes/explanations
- [ ] Agent state persistence works correctly
- [ ] Performance is acceptable (< 3s response times)

### Phase 3 Success
- [ ] Complete learning workflow from start to assessment
- [ ] n8n triggers daily and weekly workflows successfully
- [ ] CLI allows interaction with all major features
- [ ] Data flows correctly between agents and workflows

### Phase 4 Success
- [ ] System handles errors gracefully without data loss
- [ ] Documentation allows new user to set up and run system
- [ ] Personal testing shows genuine learning value
- [ ] All success metrics from CLAUDE.md are measurable

## Risk Mitigation

### Technical Risks
- **BAML API failures**: Implement retry logic and fallback prompts
- **Database corruption**: Regular backups and transaction safety
- **Agent coordination issues**: Comprehensive logging and state validation
- **Performance problems**: Profile early and optimize bottlenecks

### Schedule Risks
- **Feature creep**: Stick strictly to MVP scope, document future features
- **Integration complexity**: Test integrations continuously, not at the end
- **BAML learning curve**: Start with simple prompts, iterate complexity
- **n8n setup issues**: Have alternative local orchestration ready

## Future Python Integration

When we're ready to add Python agents:

```typescript
// TypeScript orchestrator can call Python agents
class PythonAgentRunner {
  async executeAgent(agentScript: string, context: LearningContext): Promise<AgentAction[]> {
    const contextJson = JSON.stringify(context)
    const result = await exec(`python agents/${agentScript} '${contextJson}'`)
    return JSON.parse(result)
  }
}

// Python agent example structure
// agents/ml_analytics_agent.py
// - Reads JSON context from stdin
// - Performs ML analysis (learning patterns, recommendations)
// - Returns JSON actions array
```

## Next Steps

1. **Start Phase 1**: Set up database schema and core TypeScript types
2. **Build incrementally**: Get each piece working before moving to the next
3. **Test continuously**: Validate each component as we build it
4. **Document as we go**: Keep this plan updated with learnings

This plan maintains the same comprehensive scope while being more flexible and focused on deliverables rather than artificial timelines.