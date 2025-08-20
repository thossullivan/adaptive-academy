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