import { 
  Agent, 
  AgentType, 
  AgentState, 
  AgentAction, 
  LearningContext, 
  LearningEvent,
  AsyncResult,
  AppError 
} from '../types/index.js'
import { StateManager } from '../core/StateManager.js'

/**
 * Base class for all learning agents
 * Provides common functionality for state management, logging, and error handling
 */
export abstract class BaseAgent implements Agent {
  abstract readonly type: AgentType
  protected state: Record<string, any> = {}
  protected stateManager: StateManager
  
  constructor(stateManager: StateManager) {
    this.stateManager = stateManager
  }

  // =============================================================================
  // Abstract Methods - Must be implemented by subclasses
  // =============================================================================

  /**
   * Process the current learning context and return actions to take
   */
  abstract processContext(context: LearningContext): Promise<AgentAction[]>

  /**
   * Get agent-specific name for logging and identification
   */
  protected abstract getAgentName(): string

  // =============================================================================
  // State Management
  // =============================================================================

  async updateState(event: LearningEvent): Promise<void> {
    try {
      // Update internal state based on event
      await this.handleStateUpdate(event)
      
      // Persist state to database
      const result = await this.stateManager.updateAgentState(
        event.sessionId, 
        this.type, 
        this.state
      )
      
      if (!result.success) {
        throw new Error(`Failed to persist agent state: ${result.message}`)
      }
      
      await this.logInfo(event.sessionId, 'state_updated', { 
        eventType: event.eventType,
        stateKeys: Object.keys(this.state)
      })
    } catch (error) {
      await this.logError(event.sessionId, 'state_update_failed', { error })
      throw error
    }
  }

  /**
   * Handle state updates from events - implemented by subclasses
   */
  protected async handleStateUpdate(event: LearningEvent): Promise<void> {
    // Default implementation - subclasses can override
    this.state.lastEventType = event.eventType
    this.state.lastEventTime = event.timestamp
  }

  getState(): AgentState {
    return {
      agentType: this.type,
      sessionId: 0, // Will be set when loaded from database
      lastUpdated: new Date(),
      data: { ...this.state }
    }
  }

  async loadState(sessionId: number): Promise<void> {
    try {
      const result = await this.stateManager.getAgentStates(sessionId)
      if (result.success) {
        const agentState = result.data?.find(s => s.agentType === this.type)
        if (agentState) {
          this.state = { ...agentState.data }
          await this.logInfo(sessionId, 'state_loaded', { 
            stateKeys: Object.keys(this.state) 
          })
        } else {
          // Initialize default state for new session
          await this.initializeDefaultState(sessionId)
        }
      }
    } catch (error) {
      await this.logError(sessionId, 'state_load_failed', { error })
      throw error
    }
  }

  /**
   * Initialize default state for new sessions - implemented by subclasses
   */
  protected async initializeDefaultState(sessionId: number): Promise<void> {
    this.state = {
      initialized: true,
      createdAt: new Date().toISOString(),
      sessionId
    }
    
    await this.logInfo(sessionId, 'state_initialized', { 
      agentType: this.type 
    })
  }

  async reset(): Promise<void> {
    this.state = {}
    // Note: This doesn't clear database state, just memory state
  }

  // =============================================================================
  // Action Creation Helpers
  // =============================================================================

  protected createAction(
    type: AgentAction['type'], 
    data: any, 
    priority: number = 5
  ): AgentAction {
    return {
      type,
      data,
      priority,
      agentId: this.getAgentName(),
      timestamp: new Date()
    }
  }

  protected createHighPriorityAction(
    type: AgentAction['type'], 
    data: any
  ): AgentAction {
    return this.createAction(type, data, 9)
  }

  protected createLowPriorityAction(
    type: AgentAction['type'], 
    data: any
  ): AgentAction {
    return this.createAction(type, data, 2)
  }

  // =============================================================================
  // Logging Helpers
  // =============================================================================

  protected async logInfo(
    sessionId: number, 
    eventType: string, 
    data: Record<string, any> = {}
  ): Promise<void> {
    await this.stateManager.logEvent(sessionId, eventType, {
      agent: this.getAgentName(),
      ...data
    }, this.type)
  }

  protected async logError(
    sessionId: number, 
    eventType: string, 
    data: Record<string, any> = {}
  ): Promise<void> {
    await this.stateManager.logEvent(sessionId, `error_${eventType}`, {
      agent: this.getAgentName(),
      level: 'error',
      ...data
    }, this.type)
  }

  protected async logWarning(
    sessionId: number, 
    eventType: string, 
    data: Record<string, any> = {}
  ): Promise<void> {
    await this.stateManager.logEvent(sessionId, `warning_${eventType}`, {
      agent: this.getAgentName(),
      level: 'warning',
      ...data
    }, this.type)
  }

  // =============================================================================
  // Common Helper Methods
  // =============================================================================

  /**
   * Check if enough time has passed since last action
   */
  protected hasTimeElapsed(
    lastActionTime: Date | string | undefined, 
    intervalMinutes: number
  ): boolean {
    if (!lastActionTime) return true
    
    const lastTime = new Date(lastActionTime)
    const now = new Date()
    const diffMinutes = (now.getTime() - lastTime.getTime()) / (1000 * 60)
    
    return diffMinutes >= intervalMinutes
  }

  /**
   * Check if prerequisites are met for a module
   */
  protected arePrerequisitesMet(
    modulePrerequisites: number[], 
    completedModules: number[]
  ): boolean {
    return modulePrerequisites.every(prereq => completedModules.includes(prereq))
  }

  /**
   * Get completed module IDs from context
   */
  protected getCompletedModuleIds(context: LearningContext): number[] {
    return context.availableModules
      .filter(module => module.status === 'completed')
      .map(module => module.id)
  }

  /**
   * Get in-progress module IDs from context
   */
  protected getInProgressModuleIds(context: LearningContext): number[] {
    return context.availableModules
      .filter(module => module.status === 'in_progress')
      .map(module => module.id)
  }

  /**
   * Calculate user's learning velocity (modules per week)
   */
  protected calculateLearningVelocity(context: LearningContext): number {
    const completedModules = context.availableModules.filter(m => m.status === 'completed')
    
    if (completedModules.length === 0) return 0
    
    // Get date range of completed modules
    const completionDates = completedModules
      .filter(m => m.completedAt)
      .map(m => new Date(m.completedAt!))
      .sort((a, b) => a.getTime() - b.getTime())
    
    if (completionDates.length < 2) return 0
    
    const firstCompletion = completionDates[0]
    const lastCompletion = completionDates[completionDates.length - 1]
    const weeksDiff = (lastCompletion.getTime() - firstCompletion.getTime()) / (1000 * 60 * 60 * 24 * 7)
    
    return weeksDiff > 0 ? completedModules.length / weeksDiff : 0
  }

  // =============================================================================
  // Error Handling
  // =============================================================================

  protected async handleError(
    sessionId: number, 
    operation: string, 
    error: any
  ): Promise<never> {
    const errorData = {
      operation,
      error: error instanceof Error ? error.message : String(error),
      agent: this.getAgentName(),
      timestamp: new Date().toISOString()
    }
    
    await this.logError(sessionId, 'agent_error', errorData)
    
    throw new AppError(
      `${this.getAgentName()} failed during ${operation}`,
      'AGENT_ERROR',
      errorData,
      new Date()
    )
  }
}

// Custom error class for agent-specific errors
export class AgentError extends Error {
  constructor(
    message: string,
    public agentType: AgentType,
    public operation: string,
    public context?: Record<string, any>
  ) {
    super(message)
    this.name = 'AgentError'
  }
}