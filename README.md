# Adaptive Academy - Personal MVP

## Personal Use Architecture (Claude Code Implementation)

### Core Agents (Start with 3)

1. **Curriculum Director** - Master planning and sequencing
2. **Tutor Agent** - Interactive teaching and explanations
3. **Assessment Coach** - Quizzing and progress evaluation

**Phase 2 Agents (Add Later):**

- Implementation Guide - Code reviews and project guidance
- Research Assistant - Paper recommendations and summaries
- Progress Tracker - Analytics and adaptation

### Integration Tools (MVP)

- **BAML** - Prompt management and structured outputs
- **n8n** (self-hosted) - Workflow automation
- **Obsidian** - Knowledge base and note-taking
- **SQLite** - Local progress tracking
- **GitHub** - Code repositories and version control

## BAML Integration Strategy

### Prompt Management Structure

```
baml/
├── agents/
│   ├── curriculum_director.baml
│   ├── tutor_agent.baml
│   └── assessment_coach.baml
├── schemas/
│   ├── curriculum_schema.baml
│   ├── learning_profile.baml
│   └── assessment_result.baml
└── functions/
    ├── generate_curriculum.baml
    ├── explain_concept.baml
    └── create_quiz.baml
```

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

## Simplified Agent Specifications

### 1. Curriculum Director Agent

**Core Responsibilities (MVP):**

- Generate learning roadmap for AI/ML topics
- Track module completion
- Adapt timeline based on performance

**BAML Integration:**

- Structured curriculum generation
- Progress milestone definitions
- Prerequisite validation

**Tools:**

- BAML for curriculum prompts
- SQLite for roadmap storage
- n8n for scheduling

### 2. Tutor Agent

**Core Responsibilities (MVP):**

- Explain AI/ML concepts with physics analogies
- Answer specific questions during study
- Provide multiple explanation approaches

**BAML Integration:**

- Concept explanation templates
- Learning style adaptation prompts
- Context-aware responses

**Tools:**

- BAML for teaching prompts
- Obsidian for concept linking
- Claude API for interactions

### 3. Assessment Coach Agent

**Core Responsibilities (MVP):**

- Generate quizzes for completed modules
- Track performance over time
- Identify weak areas for review

**BAML Integration:**

- Quiz generation with consistent formats
- Performance analysis prompts
- Spaced repetition scheduling

**Tools:**

- BAML for assessment prompts
- SQLite for performance data
- Simple spaced repetition logic

## n8n Workflow Simplification (MVP)

### Core Workflows Only

```
Daily Study Trigger →
├── Curriculum Director: Check today's plan
├── Tutor Agent: Deliver content
└── Assessment Coach: Check if quiz needed

Weekly Review Trigger →
├── Assessment Coach: Analyze performance
├── Curriculum Director: Adjust timeline
└── Generate progress report
```

### Removed Complexity (Add Later)

- Multi-topic curriculum generation
- Learning style detection workflows
- Age-specific adaptations
- Advanced automation triggers

## Data Models (SQLite)

### Core Tables

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

## Implementation Priority (Claude Code)

### Week 1: Foundation

1. Set up BAML with basic agent prompts
2. Create SQLite database schema
3. Build Curriculum Director with hardcoded AI/ML roadmap
4. Basic CLI interface for interaction

### Week 2: Core Agents

1. Implement Tutor Agent with BAML prompts
2. Add Assessment Coach with quiz generation
3. Simple n8n workflows for daily/weekly triggers
4. Obsidian integration for note-taking

### Week 3: Integration & Testing

1. Agent-to-agent communication via JSON
2. End-to-end learning workflow
3. Progress tracking and reporting
4. Basic performance analytics

### Week 4: Polish & Documentation

1. Error handling and logging
2. Configuration management
3. Setup documentation
4. Testing with your personal AI/ML curriculum

## Removed from MVP (Future Enhancements)

### Features to Add Later

- **Multi-topic curriculum generation** (focus on AI/ML only initially)
- **Age-specific adaptations** (adult-only for MVP)
- **Learning style detection** (use simple preferences)
- **Advanced analytics** (basic progress tracking only)
- **Research Assistant agent** (manual paper curation initially)
- **Implementation Guide agent** (basic code review prompts)
- **Complex n8n workflows** (keep workflows simple)
- **External API integrations** (Anki, Calendar, etc.)

### Technical Simplifications

- **Local-only deployment** (no cloud infrastructure)
- **Single-user system** (no multi-tenancy)
- **File-based configuration** (no admin interface)
- **Basic error handling** (no sophisticated retry logic)
- **Simple authentication** (local system only)

## Success Metrics (MVP)

### Primary Goals

- Successfully complete one AI/ML module using the system
- Demonstrate agent coordination works
- Validate BAML prompt effectiveness
- Confirm n8n workflow automation

### Measurement

- Time to complete learning modules
- Quiz performance improvement
- System reliability (uptime, error rates)
- Personal satisfaction with learning experience
