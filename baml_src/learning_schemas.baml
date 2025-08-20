// BAML schemas for Adaptive Academy learning platform
// These define type-safe interfaces for AI agent interactions

// =============================================================================
// Core Learning Types
// =============================================================================

class LearningProfile {
  background string
  learning_style string  // "visual", "analytical", "hands-on", "analogies"
  time_commitment string // e.g., "5 hours/week"
  goals string[]
  current_level string   // "beginner", "intermediate", "advanced"
}

class Explanation {
  concept string
  explanation string
  analogies string[]
  examples string[]
  follow_up_questions string[]
  related_concepts string[]
  difficulty_level int   // 1-10
}

class CurriculumModule {
  id string
  name string
  description string
  prerequisites string[]
  learning_objectives string[]
  estimated_hours int
  difficulty_level int  // 1-10
  topics string[]
}

class Curriculum {
  title string
  description string
  total_duration_weeks int
  modules CurriculumModule[]
  learning_path string[]
  milestones string[]
  assessment_strategy string
}

class Quiz {
  title string
  description string
  questions Question[]
  estimated_time_minutes int
  difficulty_level int
  learning_objectives string[]
}

class Question {
  id string
  type string           // "multiple_choice", "short_answer", "code", "essay"
  question_text string
  options string[]      // For multiple choice
  correct_answer string
  explanation string
  points int
  difficulty int        // 1-10
}

class AssessmentResult {
  quiz_id string
  score_percentage float
  time_taken_minutes int
  strengths string[]
  weak_areas string[]
  feedback string
  recommendations string[]
}

// =============================================================================
// Tutor Agent Functions
// =============================================================================

function ExplainConcept(
  concept: string,
  user_profile: LearningProfile,
  context: string
) -> Explanation {
  client GPT4
  prompt #"
    You are an expert AI/ML tutor with a PhD in both Computer Science and Physics.
    Explain the concept of {{concept}} to a student.

    Student Profile:
    - Background: {{user_profile.background}}
    - Learning Style: {{user_profile.learning_style}}
    - Current Level: {{user_profile.current_level}}
    - Goals: {{user_profile.goals}}

    Context: {{context}}

    Provide a comprehensive explanation that includes:
    1. Clear, intuitive explanation of the concept
    2. Physics analogies if the student prefers analogies
    3. Concrete examples relevant to their background
    4. Follow-up questions to deepen understanding
    5. Related concepts they should explore next

    Adapt your explanation style to match their learning preference and background.
    If they prefer analogies, use physics analogies extensively.
    Make the explanation engaging and build on concepts they already know.
  "#
}

function AnswerQuestion(
  question: string,
  concept: string,
  user_profile: LearningProfile,
  context: string
) -> Explanation {
  client GPT4
  prompt #"
    A student learning about {{concept}} has asked: "{{question}}"

    Student Profile:
    - Background: {{user_profile.background}}
    - Learning Style: {{user_profile.learning_style}}
    - Current Level: {{user_profile.current_level}}

    Learning Context: {{context}}

    Provide a helpful answer that:
    1. Directly addresses their question
    2. Explains the reasoning behind the answer
    3. Connects to the broader concept they're learning
    4. Includes examples if helpful
    5. Suggests related questions they might explore

    Match your explanation style to their learning preferences.
  "#
}

function CreatePhysicsAnalogy(
  concept: string,
  user_background: string
) -> string {
  client GPT4
  prompt #"
    Create 2-3 physics analogies to explain {{concept}} in machine learning.

    Student Background: {{user_background}}

    For each analogy:
    1. Set up the physics scenario clearly
    2. Map the ML concept elements to physics elements
    3. Explain how the analogy illuminates the ML concept
    4. Note any limitations of the analogy

    Make the analogies intuitive and memorable while being technically accurate.
    Focus on analogies that help build intuition about how {{concept}} works.
  "#
}

// =============================================================================
// Curriculum Director Functions
// =============================================================================

function GenerateCurriculum(
  learning_goal: string,
  user_profile: LearningProfile,
  timeline_weeks: int
) -> Curriculum {
  client GPT4
  prompt #"
    Create a personalized learning curriculum to achieve: {{learning_goal}}

    Student Profile:
    - Background: {{user_profile.background}}
    - Learning Style: {{user_profile.learning_style}}
    - Time Commitment: {{user_profile.time_commitment}}
    - Current Level: {{user_profile.current_level}}
    - Goals: {{user_profile.goals}}

    Timeline: {{timeline_weeks}} weeks

    Design a comprehensive curriculum that:
    1. Builds from their current knowledge level
    2. Sequences topics with proper prerequisites
    3. Matches their time availability
    4. Includes practical projects and applications
    5. Has clear milestones and checkpoints
    6. Adapts to their learning style preferences

    The curriculum should be challenging but achievable within the timeline.
  "#
}

function SequenceTopics(
  topics: string[],
  user_background: string,
  learning_goals: string[]
) -> string[] {
  client GPT4
  prompt #"
    Sequence these learning topics in optimal order: {{topics}}

    Student Background: {{user_background}}
    Learning Goals: {{learning_goals}}

    Consider:
    1. Mathematical prerequisites
    2. Conceptual dependencies
    3. Logical learning progression
    4. Cognitive load management
    5. Motivation and engagement

    Return the topics in optimal learning order with brief justification
    for the sequence chosen.
  "#
}

function AdaptCurriculum(
  current_curriculum: Curriculum,
  performance_data: map<string, float>,
  student_feedback: string
) -> Curriculum {
  client GPT4
  prompt #"
    Adapt this curriculum based on student performance and feedback:

    Current Curriculum: {{current_curriculum}}
    Performance Data: {{performance_data}}
    Student Feedback: {{student_feedback}}

    Modify the curriculum to:
    1. Address areas where student is struggling
    2. Accelerate through areas of strength
    3. Adjust difficulty based on demonstrated ability
    4. Incorporate student feedback and preferences
    5. Maintain overall learning objectives

    Return an updated curriculum with explanations for changes made.
  "#
}

// =============================================================================
// Assessment Coach Functions
// =============================================================================

function CreateQuiz(
  topic: string,
  difficulty_level: int,
  question_count: int,
  learning_objectives: string[]
) -> Quiz {
  client GPT4
  prompt #"
    Create a {{question_count}}-question quiz on {{topic}} at difficulty level {{difficulty_level}}/10.

    Learning Objectives to Assess:
    {% for objective in learning_objectives %}
    - {{objective}}
    {% endfor %}

    Create questions that:
    1. Test understanding, not just memorization
    2. Include variety: multiple choice, short answer, application problems
    3. Have well-designed distractors for multiple choice
    4. Test different levels of Bloom's taxonomy
    5. Include real-world applications where appropriate

    Each question should have:
    - Clear, unambiguous question text
    - Correct answer with explanation
    - Point value based on difficulty
    - Difficulty rating

    Make questions that reveal true understanding of the concepts.
  "#
}

function EvaluatePerformance(
  quiz_responses: map<string, string>,
  quiz: Quiz,
  student_profile: LearningProfile
) -> AssessmentResult {
  client GPT4
  prompt #"
    Evaluate student performance on this quiz:

    Quiz: {{quiz}}
    Student Responses: {{quiz_responses}}
    Student Profile: {{student_profile}}

    Provide comprehensive evaluation including:
    1. Overall score and performance analysis
    2. Strengths demonstrated in responses
    3. Knowledge gaps and misconceptions identified
    4. Specific areas needing improvement
    5. Personalized feedback for growth
    6. Recommendations for next learning steps
    7. Study strategies tailored to their learning style

    Focus on constructive feedback that helps the student improve.
  "#
}

function ProvideDetailedFeedback(
  question: Question,
  student_answer: string,
  correct_answer: string
) -> string {
  client GPT4
  prompt #"
    Provide detailed feedback on this student response:

    Question: {{question.question_text}}
    Student Answer: {{student_answer}}
    Correct Answer: {{correct_answer}}
    Question Explanation: {{question.explanation}}

    Give feedback that:
    1. Acknowledges what the student got right
    2. Clearly explains any errors or misconceptions
    3. Provides the correct understanding
    4. Connects to broader learning objectives
    5. Encourages continued learning

    Be specific, constructive, and encouraging while maintaining accuracy.
  "#
}

function IdentifyLearningGaps(
  assessment_history: AssessmentResult[],
  curriculum_area: string
) -> string[] {
  client GPT4
  prompt #"
    Analyze learning gaps from assessment history in {{curriculum_area}}:

    Assessment History:
    {% for assessment in assessment_history %}
    - Score: {{assessment.score_percentage}}%, Weak Areas: {{assessment.weak_areas}}, Date: Recent
    {% endfor %}

    Identify:
    1. Persistent knowledge gaps across assessments
    2. Fundamental vs. advanced concept gaps
    3. Skills vs. knowledge gaps
    4. Prerequisites that may be missing
    5. Patterns in misconceptions

    Return prioritized list of learning gaps that should be addressed first.
  "#
}

// =============================================================================
// Developer Crew Project Management Types
// =============================================================================

enum TechnologyStack {
  NextJS
  React
  TypeScript
  Python
  FastAPI
  Django
  Flask
  PostgreSQL
  SQLite
  MongoDB
  Redis
  Docker
  NodeJS
  TailwindCSS
  ShadcnUI
  Prisma
  Supabase
  Vercel
  AWS
  Firebase
}

enum ProjectComplexity {
  Simple
  Moderate
  Complex
  VeryComplex
}

enum ProjectTemplate {
  NextJSDashboard
  ReactApp
  PythonAPI
  FullStackApp
  DataPipeline
  MLModel
  MobileApp
  DesktopApp
  WebScraper
  ChatBot
  ECommerce
  Blog
  Portfolio
  LandingPage
  AdminPanel
}

class ProjectComplexityAnalysis {
  overall_complexity ProjectComplexity
  technical_complexity_score float // 1.0 to 10.0
  integration_complexity_score float // 1.0 to 10.0
  deployment_complexity_score float // 1.0 to 10.0
  maintenance_complexity_score float // 1.0 to 10.0
  key_complexity_factors string[]
  recommendations string[]
  estimated_development_time string
  required_expertise_level string // "junior", "mid", "senior", "expert"
  potential_blockers string[]
  complexity_justification string
}

enum RiskLevel {
  Low
  Medium
  High
  Critical
}

enum PhaseStatus {
  Planned
  InProgress
  Completed
  Blocked
  Failed
}

enum EstimatedEffort {
  OneToTwoHours
  TwoToFourHours
  HalfDay
  OneDay
  TwoToThreeDays
  OneWeek
  TwoWeeks
  OneMonth
}

enum GitStrategy {
  FeatureBranch
  ContinueBranch
  NewBranch
  HotfixBranch
  ReleaseBranch
  DirectToMain
}

class Risk {
  description string
  level RiskLevel
  mitigation_strategy string
  impact string
}

class AcceptanceCriterion {
  description string
  testable bool
  priority int // 1-5, where 1 is highest priority
}

class Dependency {
  phase_number int
  description string
  type string // "hard" or "soft"
}

class Deliverable {
  name string
  description string
  file_path string?
  acceptance_criteria AcceptanceCriterion[]
}

class ProjectPhase {
  phase_number int
  phase_name string
  description string
  deliverables Deliverable[]
  estimated_effort EstimatedEffort
  dependencies Dependency[]
  git_strategy GitStrategy
  acceptance_criteria AcceptanceCriterion[]
  potential_risks Risk[]
  prerequisites string[]
  success_metrics string[]
  status PhaseStatus
}

class IntegrationPlan {
  strategy string
  testing_approach string
  deployment_steps string[]
  rollback_plan string
  monitoring_requirements string[]
}

class DeploymentConsiderations {
  environment_setup string[]
  infrastructure_requirements string[]
  security_considerations string[]
  performance_requirements string[]
  scaling_considerations string[]
  backup_strategy string
  monitoring_setup string[]
}

class ProjectPlan {
  project_summary string
  technology_stack TechnologyStack[]
  phases ProjectPhase[]
  integration_plan IntegrationPlan
  deployment_considerations DeploymentConsiderations
  total_estimated_effort string
  critical_path_phases int[]
  success_metrics string[]
  assumptions string[]
  constraints string[]
  stakeholders string[]
  budget_considerations string?
  timeline_milestones map<string, string>
}

// =============================================================================
// Project Management Functions
// =============================================================================

function GenerateProjectPlan(
  task_description: string,
  working_directory: string,
  existing_tech_stack: string[]
) -> ProjectPlan {
  client Anthropic
  prompt #"
    You are an expert Project Manager. Create a comprehensive project plan for this task:

    Task: {{task_description}}
    Working Directory: {{working_directory}}
    Existing Technology Stack: {{existing_tech_stack}}

    Break this into 3-8 logical phases. Each phase should be 1-6 hours of work with clear deliverables.

    Provide a detailed project summary, list the technology stack to use, create phases with deliverables and acceptance criteria, include integration and deployment plans, estimate total effort, identify success metrics, list assumptions and constraints, and specify key stakeholders and timeline milestones.
  "#
}

function AnalyzeProjectComplexity(
  project_summary: string,
  technology_stack: TechnologyStack[]
) -> ProjectComplexityAnalysis {
  client Anthropic
  prompt #"
    Analyze the complexity of this software development project:

    Project Summary: {{project_summary}}
    Technology Stack: {{technology_stack}}

    Provide a comprehensive complexity analysis considering:

    1. Technical Complexity (1-10):
       - Number and variety of technologies
       - Integration complexity between components
       - Custom vs off-the-shelf solutions
       - Algorithm complexity requirements

    2. Integration Complexity (1-10):
       - Third-party API integrations
       - Database integration complexity
       - Authentication and authorization systems
       - Cross-platform considerations

    3. Deployment Complexity (1-10):
       - Infrastructure requirements
       - CI/CD pipeline needs
       - Environment configuration
       - Scaling considerations

    4. Maintenance Complexity (1-10):
       - Code maintainability
       - Update frequency requirements
       - Monitoring and debugging needs
       - Documentation requirements

    Consider the technology stack interactions, potential integration challenges, and overall project scope.
    Provide specific recommendations for managing complexity and potential blockers to watch for.
  "#
}

function GetProjectTemplate(
  template_type: ProjectTemplate,
  customizations: string[]
) -> ProjectPlan {
  client Anthropic
  prompt #"
    Generate a detailed project plan based on the {{template_type}} template with these customizations:
    {{customizations}}

    Create a comprehensive project plan that includes:

    1. Technology stack appropriate for {{template_type}}
    2. Phase breakdown optimized for this template type
    3. Template-specific deliverables and acceptance criteria
    4. Common patterns and best practices for {{template_type}}
    5. Integration considerations specific to this template
    6. Deployment strategy appropriate for {{template_type}}

    Customize the plan based on the provided requirements while maintaining the core structure and best practices of the {{template_type}} template.

    Ensure phases are:
    - Logical and sequential
    - Appropriately sized (1-6 hours each)
    - Include realistic deliverables
    - Have clear acceptance criteria
    - Consider template-specific risks and mitigations
  "#
}

function ValidateProjectPhase(
  phase_name: string,
  phase_description: string,
  estimated_effort: EstimatedEffort,
  deliverables: Deliverable[],
  project_context: string
) -> PhaseValidationResult {
  client Anthropic
  prompt #"
    Validate this project phase for feasibility and completeness:

    Phase: {{phase_name}}
    Description: {{phase_description}}
    Estimated Effort: {{estimated_effort}}
    Deliverables: {{deliverables}}

    Project Context: {{project_context}}

    Assess:
    1. Is the effort estimate realistic?
    2. Are deliverables clearly defined and achievable?
    3. Are there missing dependencies or risks?
    4. Are acceptance criteria testable?

    Provide validation results with specific recommendations for improvement.
  "#
}

class PhaseValidationResult {
  is_valid bool
  confidence_score float // 0.0 to 1.0
  issues ValidationIssue[]
  recommendations string[]
  adjusted_effort_estimate EstimatedEffort?
}

enum ValidationIssueType {
  UnrealisticEffort
  UnclearDeliverables
  MissingDependencies
  UntestedAcceptanceCriteria
  HighRiskPhase
  TechnicalComplexity
}

class ValidationIssue {
  type ValidationIssueType
  severity RiskLevel
  description string
  suggested_fix string
}

// =============================================================================
// Client Configuration
// =============================================================================

client<llm> GPT4 {
  provider "openai"
  options {
    model "gpt-4"
    temperature 0.7
    max_tokens 2000
    api_key env.OPENAI_API_KEY
  }
}

client<llm> Anthropic {
  provider "anthropic"
  options {
    model "claude-3-5-sonnet-20241022"
    temperature 0.3
    max_tokens 4000
    api_key env.ANTHROPIC_API_KEY
  }
}
