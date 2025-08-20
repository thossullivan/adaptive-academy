import sqlite3 from 'sqlite3'
import { open, Database } from 'sqlite'
import { 
  LearningContext, 
  LearningSession, 
  Module, 
  UserProfile, 
  AgentState, 
  LearningEvent, 
  Assessment, 
  PerformanceMetrics,
  LearningGoal,
  AgentType,
  AsyncResult,
  AppError,
  DatabaseConnection
} from '../types/index.js'

export class StateManager implements DatabaseConnection {
  private db: Database | null = null
  private readonly dbPath: string

  constructor(dbPath: string = './database/adaptive-academy.db') {
    this.dbPath = dbPath
  }

  // =============================================================================
  // Database Connection Management
  // =============================================================================

  async initialize(): Promise<void> {
    try {
      this.db = await open({
        filename: this.dbPath,
        driver: sqlite3.Database
      })

      // Enable foreign keys and WAL mode for better performance
      await this.db.exec('PRAGMA foreign_keys = ON')
      await this.db.exec('PRAGMA journal_mode = WAL')
      await this.db.exec('PRAGMA synchronous = NORMAL')
      
      console.log(`Database initialized: ${this.dbPath}`)
    } catch (error) {
      throw new AppError('Failed to initialize database', 'DB_INIT_ERROR', { error })
    }
  }

  async close(): Promise<void> {
    if (this.db) {
      await this.db.close()
      this.db = null
    }
  }

  private ensureConnection(): Database {
    if (!this.db) {
      throw new AppError('Database not initialized', 'DB_NOT_INITIALIZED')
    }
    return this.db
  }

  // =============================================================================
  // Generic Database Operations
  // =============================================================================

  async query<T = any>(sql: string, params: any[] = []): Promise<T[]> {
    const db = this.ensureConnection()
    try {
      return await db.all(sql, params)
    } catch (error) {
      throw new AppError(`Query failed: ${sql}`, 'QUERY_ERROR', { error, params })
    }
  }

  async run(sql: string, params: any[] = []): Promise<{ lastID?: number; changes: number }> {
    const db = this.ensureConnection()
    try {
      return await db.run(sql, params)
    } catch (error) {
      throw new AppError(`Run failed: ${sql}`, 'RUN_ERROR', { error, params })
    }
  }

  async transaction<T>(fn: () => Promise<T>): Promise<T> {
    const db = this.ensureConnection()
    await db.exec('BEGIN TRANSACTION')
    try {
      const result = await fn()
      await db.exec('COMMIT')
      return result
    } catch (error) {
      await db.exec('ROLLBACK')
      throw error
    }
  }

  // =============================================================================
  // Learning Context Management
  // =============================================================================

  async getLearningContext(sessionId: number): AsyncResult<LearningContext> {
    try {
      const session = await this.getSession(sessionId)
      if (!session.success) {
        return session
      }

      const userProfile = await this.getUserProfile(session.data!.userId)
      if (!userProfile.success) {
        return userProfile
      }

      const currentModule = session.data!.currentModuleId 
        ? await this.getModule(session.data!.currentModuleId)
        : { success: true, data: undefined }

      const [agentStates, eventHistory, learningGoals, availableModules, recentAssessments, performanceData] = await Promise.all([
        this.getAgentStates(sessionId),
        this.getRecentEvents(sessionId, 50),
        this.getLearningGoals(session.data!.userId),
        this.getAvailableModules(session.data!.userId),
        this.getRecentAssessments(sessionId, 5),
        this.getPerformanceMetrics(session.data!.userId)
      ])

      const context: LearningContext = {
        sessionId,
        userId: session.data!.userId,
        currentModule: currentModule.data,
        learningGoals: learningGoals.data || [],
        performanceData: performanceData.data || this.getDefaultPerformanceMetrics(session.data!.userId),
        agentStates: this.formatAgentStates(agentStates.data || []),
        eventHistory: eventHistory.data || [],
        userProfile: userProfile.data!,
        preferences: userProfile.data!.preferences,
        sessionState: session.data!.sessionState,
        availableModules: availableModules.data || [],
        recentAssessments: recentAssessments.data || []
      }

      return { success: true, data: context }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get learning context' }
    }
  }

  private formatAgentStates(states: AgentState[]): Record<AgentType, AgentState> {
    const formatted: Record<AgentType, AgentState> = {} as any
    states.forEach(state => {
      formatted[state.agentType] = state
    })
    return formatted
  }

  // =============================================================================
  // Session Management
  // =============================================================================

  async createSession(userId: number, sessionType: 'study' | 'review' | 'assessment' = 'study'): AsyncResult<LearningSession> {
    try {
      const result = await this.run(
        `INSERT INTO learning_sessions (user_id, session_type, session_state) 
         VALUES (?, ?, ?)`,
        [userId, sessionType, JSON.stringify({ currentPhase: 'starting', progressInModule: 0, timeSpent: 0, conceptsCovered: [], questionsAnswered: 0, lastActivity: 'session_created' })]
      )

      if (result.lastID) {
        const session = await this.getSession(result.lastID)
        await this.logEvent(result.lastID, 'session_started', { sessionType })
        return session
      }

      return { success: false, message: 'Failed to create session' }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to create session' }
    }
  }

  async getSession(sessionId: number): AsyncResult<LearningSession> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM learning_sessions WHERE id = ?',
        [sessionId]
      )

      if (rows.length === 0) {
        return { success: false, message: 'Session not found' }
      }

      const row = rows[0]
      const session: LearningSession = {
        id: row.id,
        userId: row.user_id,
        startedAt: new Date(row.started_at),
        endedAt: row.ended_at ? new Date(row.ended_at) : undefined,
        currentModuleId: row.current_module_id,
        sessionState: JSON.parse(row.session_state || '{}'),
        sessionType: row.session_type
      }

      return { success: true, data: session }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get session' }
    }
  }

  async updateSessionState(sessionId: number, updates: Partial<LearningSession>): AsyncResult<void> {
    try {
      const setParts: string[] = []
      const params: any[] = []

      if (updates.currentModuleId !== undefined) {
        setParts.push('current_module_id = ?')
        params.push(updates.currentModuleId)
      }

      if (updates.sessionState !== undefined) {
        setParts.push('session_state = ?')
        params.push(JSON.stringify(updates.sessionState))
      }

      if (updates.endedAt !== undefined) {
        setParts.push('ended_at = ?')
        params.push(updates.endedAt.toISOString())
      }

      if (setParts.length === 0) {
        return { success: true }
      }

      params.push(sessionId)
      
      await this.run(
        `UPDATE learning_sessions SET ${setParts.join(', ')} WHERE id = ?`,
        params
      )

      return { success: true }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to update session state' }
    }
  }

  // =============================================================================
  // User Profile Management
  // =============================================================================

  async getUserProfile(userId: number): AsyncResult<UserProfile> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM user_profile WHERE id = ?',
        [userId]
      )

      if (rows.length === 0) {
        return { success: false, message: 'User profile not found' }
      }

      const row = rows[0]
      const profile: UserProfile = {
        id: row.id,
        background: row.background,
        hoursPerDay: row.hours_per_day,
        learningStyle: row.learning_style,
        currentFocus: row.current_focus,
        preferences: JSON.parse(row.preferences || '{}'),
        createdAt: new Date(row.created_at),
        updatedAt: new Date(row.updated_at)
      }

      return { success: true, data: profile }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get user profile' }
    }
  }

  // =============================================================================
  // Module Management
  // =============================================================================

  async getModule(moduleId: number): AsyncResult<Module> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM curriculum WHERE id = ?',
        [moduleId]
      )

      if (rows.length === 0) {
        return { success: false, message: 'Module not found' }
      }

      const row = rows[0]
      const module: Module = {
        id: row.id,
        topic: row.topic,
        moduleName: row.module_name,
        description: row.description,
        prerequisites: JSON.parse(row.prerequisites || '[]'),
        estimatedHours: row.estimated_hours,
        difficultyLevel: row.difficulty_level,
        status: row.status,
        createdAt: new Date(row.created_at),
        completedAt: row.completed_at ? new Date(row.completed_at) : undefined
      }

      return { success: true, data: module }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get module' }
    }
  }

  async getAvailableModules(userId: number): AsyncResult<Module[]> {
    try {
      // Get modules that are either not started or in progress
      // and have their prerequisites completed
      const rows = await this.query<any>(`
        SELECT c.* FROM curriculum c
        WHERE c.status IN ('not_started', 'in_progress')
        ORDER BY c.difficulty_level, c.id
      `)

      const modules: Module[] = rows.map(row => ({
        id: row.id,
        topic: row.topic,
        moduleName: row.module_name,
        description: row.description,
        prerequisites: JSON.parse(row.prerequisites || '[]'),
        estimatedHours: row.estimated_hours,
        difficultyLevel: row.difficulty_level,
        status: row.status,
        createdAt: new Date(row.created_at),
        completedAt: row.completed_at ? new Date(row.completed_at) : undefined
      }))

      return { success: true, data: modules }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get available modules' }
    }
  }

  // =============================================================================
  // Agent State Management
  // =============================================================================

  async getAgentStates(sessionId: number): AsyncResult<AgentState[]> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM agent_states WHERE session_id = ?',
        [sessionId]
      )

      const states: AgentState[] = rows.map(row => ({
        agentType: row.agent_type,
        sessionId: row.session_id,
        lastUpdated: new Date(row.last_updated),
        data: JSON.parse(row.state_data || '{}')
      }))

      return { success: true, data: states }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get agent states' }
    }
  }

  async updateAgentState(sessionId: number, agentType: AgentType, stateData: Record<string, any>): AsyncResult<void> {
    try {
      await this.run(`
        INSERT OR REPLACE INTO agent_states (session_id, agent_type, state_data, last_updated)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
      `, [sessionId, agentType, JSON.stringify(stateData)])

      return { success: true }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to update agent state' }
    }
  }

  // =============================================================================
  // Event Logging
  // =============================================================================

  async logEvent(sessionId: number, eventType: string, eventData: Record<string, any> = {}, agentType?: AgentType): AsyncResult<void> {
    try {
      await this.run(
        'INSERT INTO learning_events (session_id, agent_type, event_type, event_data) VALUES (?, ?, ?, ?)',
        [sessionId, agentType || null, eventType, JSON.stringify(eventData)]
      )

      return { success: true }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to log event' }
    }
  }

  async getRecentEvents(sessionId: number, limit: number = 20): AsyncResult<LearningEvent[]> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM learning_events WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?',
        [sessionId, limit]
      )

      const events: LearningEvent[] = rows.map(row => ({
        id: row.id,
        sessionId: row.session_id,
        agentType: row.agent_type,
        eventType: row.event_type,
        eventData: JSON.parse(row.event_data || '{}'),
        timestamp: new Date(row.timestamp)
      }))

      return { success: true, data: events }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get recent events' }
    }
  }

  // =============================================================================
  // Assessment Management
  // =============================================================================

  async getRecentAssessments(sessionId: number, limit: number = 5): AsyncResult<Assessment[]> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM assessments WHERE session_id = ? ORDER BY created_at DESC LIMIT ?',
        [sessionId, limit]
      )

      const assessments: Assessment[] = rows.map(row => ({
        id: row.id,
        sessionId: row.session_id,
        moduleId: row.module_id,
        quizData: JSON.parse(row.quiz_data || '{}'),
        userResponses: JSON.parse(row.user_responses || '[]'),
        score: row.score,
        completionTime: row.completion_time,
        weakAreas: JSON.parse(row.weak_areas || '[]'),
        strengths: JSON.parse(row.strengths || '[]'),
        createdAt: new Date(row.created_at)
      }))

      return { success: true, data: assessments }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get recent assessments' }
    }
  }

  // =============================================================================
  // Learning Goals Management
  // =============================================================================

  async getLearningGoals(userId: number): AsyncResult<LearningGoal[]> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM learning_goals WHERE user_id = ? AND status = "active" ORDER BY priority DESC',
        [userId]
      )

      const goals: LearningGoal[] = rows.map(row => ({
        id: row.id,
        userId: row.user_id,
        goalType: row.goal_type,
        title: row.title,
        description: row.description,
        targetModules: JSON.parse(row.target_modules || '[]'),
        targetDate: row.target_date ? new Date(row.target_date) : undefined,
        priority: row.priority,
        status: row.status,
        progressPercentage: row.progress_percentage,
        createdAt: new Date(row.created_at)
      }))

      return { success: true, data: goals }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get learning goals' }
    }
  }

  // =============================================================================
  // Performance Metrics
  // =============================================================================

  async getPerformanceMetrics(userId: number): AsyncResult<PerformanceMetrics> {
    try {
      const rows = await this.query<any>(
        'SELECT * FROM user_performance WHERE user_id = ?',
        [userId]
      )

      if (rows.length === 0) {
        return { success: true, data: this.getDefaultPerformanceMetrics(userId) }
      }

      const row = rows[0]
      const metrics: PerformanceMetrics = {
        userId: row.user_id,
        totalSessions: row.total_sessions || 0,
        completedModules: row.completed_modules || 0,
        activeModules: row.active_modules || 0,
        averageQuizScore: row.average_quiz_score || 0,
        totalStudyHours: row.total_study_hours || 0,
        learningVelocity: 0, // Calculate separately
        conceptMastery: {}, // Calculate separately
        weakAreas: [],
        strengths: []
      }

      return { success: true, data: metrics }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to get performance metrics' }
    }
  }

  private getDefaultPerformanceMetrics(userId: number): PerformanceMetrics {
    return {
      userId,
      totalSessions: 0,
      completedModules: 0,
      activeModules: 0,
      averageQuizScore: 0,
      totalStudyHours: 0,
      learningVelocity: 0,
      conceptMastery: {},
      weakAreas: [],
      strengths: []
    }
  }

  // =============================================================================
  // Database Schema Setup
  // =============================================================================

  async setupSchema(): AsyncResult<void> {
    try {
      const fs = await import('fs/promises')
      const path = await import('path')
      
      const schemaPath = path.join(process.cwd(), 'database', 'schema.sql')
      const schema = await fs.readFile(schemaPath, 'utf-8')
      
      await this.db!.exec(schema)
      return { success: true }
    } catch (error) {
      return { success: false, error: error as AppError, message: 'Failed to setup database schema' }
    }
  }
}

