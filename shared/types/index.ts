// Core types for the Adaptive Academy learning system

// =============================================================================
// User and Profile Types
// =============================================================================

export interface UserProfile {
  id: number
  background: string
  hoursPerDay: number
  learningStyle: 'visual' | 'auditory' | 'kinesthetic' | 'reading'
  currentFocus: string
  preferences: UserPreferences
  createdAt: Date
  updatedAt: Date
}

export interface UserPreferences {
  explanationStyle: 'physics_analogies' | 'code_examples' | 'step_by_step' | 'visual_diagrams'
  difficultyPreference: 'easy_start' | 'progressive' | 'challenge_first'
  assessmentFrequency: 'daily' | 'weekly' | 'module_completion'
  reminderEnabled: boolean
  [key: string]: any // Allow for future preference additions
}

// =============================================================================
// Learning Content Types
// =============================================================================

export interface Module {
  id: number
  topic: string
  moduleName: string
  description: string
  prerequisites: number[] // Module IDs
  estimatedHours: number
  difficultyLevel: number // 1-10
  status: 'not_started' | 'in_progress' | 'completed'
  createdAt: Date
  completedAt?: Date
}

export interface LearningGoal {
  id: number
  userId: number
  goalType: 'skill' | 'knowledge' | 'project' | 'certification'
  title: string
  description: string
  targetModules: number[] // Module IDs that contribute to this goal
  targetDate?: Date
  priority: number // 1-10
  status: 'active' | 'completed' | 'paused'
  progressPercentage: number // 0-100
  createdAt: Date
}

// =============================================================================
// Session and State Types
// =============================================================================

export interface LearningSession {
  id: number
  userId: number
  startedAt: Date
  endedAt?: Date
  currentModuleId?: number
  sessionState: SessionState
  sessionType: 'study' | 'review' | 'assessment'
}

export interface SessionState {
  currentPhase: 'starting' | 'learning' | 'practicing' | 'assessing' | 'reviewing' | 'completed'
  progressInModule: number // 0-100 percentage
  timeSpent: number // minutes
  conceptsCovered: string[]
  questionsAnswered: number
  lastActivity: string
  [key: string]: any // Flexible state storage
}

// =============================================================================
// Agent Types
// =============================================================================

export type AgentType = 'curriculum_director' | 'tutor' | 'assessment_coach'

export interface Agent {
  type: AgentType
  processContext(context: LearningContext): Promise<AgentAction[]>
  updateState(event: LearningEvent): Promise<void>
  getState(): AgentState
  reset(): Promise<void>
}

export interface AgentState {
  agentType: AgentType
  sessionId: number
  lastUpdated: Date
  data: Record<string, any> // Agent-specific state data
}

export interface AgentAction {
  type: 'update_curriculum' | 'provide_explanation' | 'generate_quiz' | 'log_event' | 'schedule_review' | 'recommend_module'
  data: any
  priority: number // 1-10, higher is more important
  agentId: string
  timestamp: Date
}

// =============================================================================
// Assessment Types
// =============================================================================

export interface Assessment {
  id: number
  sessionId: number
  moduleId: number
  quizData: QuizData
  userResponses: QuizResponse[]
  score: number // 0-100
  completionTime: number // seconds
  weakAreas: string[]
  strengths: string[]
  createdAt: Date
}

export interface QuizData {
  questions: QuizQuestion[]
  timeLimit?: number // seconds
  instructions: string
}

export interface QuizQuestion {
  id: string
  type: 'multiple_choice' | 'true_false' | 'short_answer' | 'code_completion'
  question: string
  options?: string[] // For multiple choice
  correctAnswer: string | string[]
  explanation: string
  difficulty: number // 1-10
  concept: string // What concept this tests
}

export interface QuizResponse {
  questionId: string
  userAnswer: string | string[]
  isCorrect: boolean
  timeSpent: number // seconds
  confidence?: number // 1-5 self-reported confidence
}

// =============================================================================
// Performance and Analytics Types
// =============================================================================

export interface PerformanceMetrics {
  userId: number
  totalSessions: number
  completedModules: number
  activeModules: number
  averageQuizScore: number
  totalStudyHours: number
  learningVelocity: number // modules completed per week
  conceptMastery: Record<string, number> // concept -> mastery level (0-100)
  weakAreas: string[]
  strengths: string[]
}

export interface PerformanceMetric {
  id: number
  sessionId: number
  moduleId?: number
  metricType: 'completion_time' | 'quiz_score' | 'concept_mastery' | 'engagement' | 'retention'
  metricValue: number
  metadata: Record<string, any>
  recordedAt: Date
}

// =============================================================================
// Event and Logging Types
// =============================================================================

export interface LearningEvent {
  id: number
  sessionId: number
  agentType?: AgentType
  eventType: string
  eventData: Record<string, any>
  timestamp: Date
}

export type EventType = 
  | 'session_started'
  | 'session_ended'
  | 'module_started'
  | 'module_completed'
  | 'concept_explained'
  | 'quiz_completed'
  | 'performance_analyzed'
  | 'curriculum_updated'
  | 'goal_achieved'
  | 'agent_action'
  | 'error_occurred'

// =============================================================================
// Core Learning Context
// =============================================================================

export interface LearningContext {
  sessionId: number
  userId: number
  currentModule?: Module
  learningGoals: LearningGoal[]
  performanceData: PerformanceMetrics
  agentStates: Record<AgentType, AgentState>
  eventHistory: LearningEvent[]
  userProfile: UserProfile
  preferences: UserPreferences
  sessionState: SessionState
  availableModules: Module[]
  recentAssessments: Assessment[]
}

// =============================================================================
// Curriculum and Learning Path Types
// =============================================================================

export interface Curriculum {
  id: string
  topic: string
  modules: Module[]
  learningPath: LearningPath
  estimatedTotalHours: number
  difficultyProgression: number[]
}

export interface LearningPath {
  moduleSequence: number[] // Ordered module IDs
  branchingPoints: BranchingPoint[]
  prerequisites: Record<number, number[]> // moduleId -> prerequisite moduleIds
  recommendations: PathRecommendation[]
}

export interface BranchingPoint {
  moduleId: number
  condition: string // e.g., "quiz_score > 80"
  truePath: number[] // module IDs to follow if condition is true
  falsePath: number[] // module IDs to follow if condition is false
}

export interface PathRecommendation {
  moduleId: number
  reason: string
  confidence: number // 0-100
  basedOn: 'performance' | 'preferences' | 'goals' | 'time_available'
}

// =============================================================================
// Explanation and Teaching Types
// =============================================================================

export interface Explanation {
  concept: string
  explanation: string
  analogies: string[]
  examples: string[]
  visualAids?: string[] // URLs or descriptions
  followUpQuestions: string[]
  relatedConcepts: string[]
  difficultyLevel: number
}

export interface TeachingContext {
  currentConcept: string
  userUnderstanding: number // 0-100 estimated understanding
  previousExplanations: string[]
  preferredStyle: UserPreferences['explanationStyle']
  availableTime: number // minutes
  relatedKnowledge: string[]
}

// =============================================================================
// Configuration and System Types
// =============================================================================

export interface SystemConfig {
  database: {
    path: string
    backupInterval: number // hours
  }
  agents: {
    responseTimeout: number // seconds
    maxRetries: number
    logLevel: 'debug' | 'info' | 'warn' | 'error'
  }
  llm: {
    provider: 'claude' | 'openai' | 'local'
    apiKey?: string
    model: string
    temperature: number
    maxTokens: number
  }
  learning: {
    defaultSessionLength: number // minutes
    assessmentThreshold: number // score needed to pass
    spacedRepetitionEnabled: boolean
  }
}

export interface DatabaseConnection {
  query<T = any>(sql: string, params?: any[]): Promise<T[]>
  run(sql: string, params?: any[]): Promise<{ lastID?: number; changes: number }>
  close(): Promise<void>
  transaction<T>(fn: () => Promise<T>): Promise<T>
}

// =============================================================================
// Error and Result Types
// =============================================================================

export interface Result<T, E = Error> {
  success: boolean
  data?: T
  error?: E
  message?: string
}

export class AppError extends Error {
  constructor(
    message: string,
    public code: string,
    public context?: Record<string, any>,
    public timestamp: Date = new Date()
  ) {
    super(message)
    this.name = 'AppError'
  }
}

export type AsyncResult<T, E = AppError> = Promise<Result<T, E>>

// =============================================================================
// Utility Types
// =============================================================================

export type Partial<T> = {
  [P in keyof T]?: T[P]
}

export type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P]
}

export type ID = number | string

export type Timestamp = Date | string

// JSON serializable type for database storage
export type JSONSerializable = 
  | string 
  | number 
  | boolean 
  | null 
  | JSONSerializable[] 
  | { [key: string]: JSONSerializable }

// =============================================================================
// Type Guards
// =============================================================================

export function isAgentType(value: string): value is AgentType {
  return ['curriculum_director', 'tutor', 'assessment_coach'].includes(value)
}

export function isEventType(value: string): value is EventType {
  const eventTypes: EventType[] = [
    'session_started', 'session_ended', 'module_started', 'module_completed',
    'concept_explained', 'quiz_completed', 'performance_analyzed', 
    'curriculum_updated', 'goal_achieved', 'agent_action', 'error_occurred'
  ]
  return eventTypes.includes(value as EventType)
}

export function isLearningStyle(value: string): value is UserProfile['learningStyle'] {
  return ['visual', 'auditory', 'kinesthetic', 'reading'].includes(value)
}