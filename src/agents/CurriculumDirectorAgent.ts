import { 
  AgentType, 
  AgentAction, 
  LearningContext, 
  LearningEvent,
  Module,
  LearningGoal
} from '../types/index.js'
import { BaseAgent } from './BaseAgent.js'
import { StateManager } from '../core/StateManager.js'

interface CurriculumDirectorState {
  lastCurriculumGeneration?: string
  lastTimelineAdjustment?: string
  currentRecommendations: ModuleRecommendation[]
  adaptationHistory: CurriculumAdaptation[]
  focusAreas: string[]
  difficultyProgression: number
  estimatedCompletionDate?: string
}

interface ModuleRecommendation {
  moduleId: number
  reason: string
  priority: number
  estimatedStartDate: string
  confidence: number // 0-100
}

interface CurriculumAdaptation {
  date: string
  reason: string
  changes: string[]
  triggerEvent: string
}

/**
 * Curriculum Director Agent
 * 
 * Responsibilities:
 * - Generate and maintain learning roadmaps
 * - Adapt curriculum based on performance and goals
 * - Recommend next modules and learning paths
 * - Track progress against learning objectives
 * - Adjust timelines based on learning velocity
 */
export class CurriculumDirectorAgent extends BaseAgent {
  readonly type: AgentType = 'curriculum_director'
  
  constructor(stateManager: StateManager) {
    super(stateManager)
  }

  protected getAgentName(): string {
    return 'Curriculum Director'
  }

  // =============================================================================
  // Main Processing Logic
  // =============================================================================

  async processContext(context: LearningContext): Promise<AgentAction[]> {
    try {
      await this.loadState(context.sessionId)
      
      const actions: AgentAction[] = []
      const state = this.state as CurriculumDirectorState

      // 1. Check if we need to generate initial curriculum
      if (this.shouldGenerateInitialCurriculum(context, state)) {
        const curriculumAction = await this.generateInitialCurriculum(context)
        actions.push(curriculumAction)
        await this.logInfo(context.sessionId, 'curriculum_generated', {
          moduleCount: context.availableModules.length
        })
      }

      // 2. Check if curriculum needs adaptation
      if (this.shouldAdaptCurriculum(context, state)) {
        const adaptationActions = await this.adaptCurriculum(context)
        actions.push(...adaptationActions)
        await this.logInfo(context.sessionId, 'curriculum_adapted', {
          adaptationCount: adaptationActions.length
        })
      }

      // 3. Generate module recommendations
      if (this.shouldUpdateRecommendations(context, state)) {
        const recommendationAction = await this.updateRecommendations(context)
        actions.push(recommendationAction)
        await this.logInfo(context.sessionId, 'recommendations_updated', {
          recommendationCount: state.currentRecommendations.length
        })
      }

      // 4. Check learning goals progress
      if (this.shouldCheckGoalProgress(context, state)) {
        const goalActions = await this.checkGoalProgress(context)
        actions.push(...goalActions)
      }

      // 5. Update difficulty progression
      if (this.shouldUpdateDifficulty(context, state)) {
        const difficultyAction = await this.updateDifficultyProgression(context)
        actions.push(difficultyAction)
      }

      // Update our state with latest analysis
      await this.updateInternalState(context)

      return actions.sort((a, b) => b.priority - a.priority)
    } catch (error) {
      return await this.handleError(context.sessionId, 'processContext', error)
    }
  }

  // =============================================================================
  // Decision Logic
  // =============================================================================

  private shouldGenerateInitialCurriculum(
    context: LearningContext, 
    state: CurriculumDirectorState
  ): boolean {
    // Generate if no previous generation or user focus has changed significantly
    if (!state.lastCurriculumGeneration) return true
    
    // Check if user's focus has changed
    const previousFocus = state.focusAreas || []
    const currentFocus = [context.userProfile.currentFocus]
    
    return !this.arraysEqual(previousFocus, currentFocus)
  }

  private shouldAdaptCurriculum(
    context: LearningContext, 
    state: CurriculumDirectorState
  ): boolean {
    // Adapt if performance indicates need for change
    const recentAssessments = context.recentAssessments.slice(0, 3)
    if (recentAssessments.length === 0) return false

    // Check for consistently low scores
    const averageScore = recentAssessments.reduce((sum, a) => sum + a.score, 0) / recentAssessments.length
    if (averageScore < 70) return true

    // Check for consistently high scores (maybe too easy)
    if (averageScore > 95) return true

    // Check if learning velocity has changed significantly
    const currentVelocity = this.calculateLearningVelocity(context)
    const expectedVelocity = context.userProfile.hoursPerDay / 10 // Rough estimate
    
    return Math.abs(currentVelocity - expectedVelocity) > expectedVelocity * 0.5
  }

  private shouldUpdateRecommendations(
    context: LearningContext, 
    state: CurriculumDirectorState
  ): boolean {
    // Update recommendations every session or when module completed
    const lastUpdate = state.lastTimelineAdjustment
    if (!lastUpdate) return true

    // Check if a module was completed recently
    const recentCompletions = context.eventHistory.filter(e => 
      e.eventType === 'module_completed' && 
      this.hasTimeElapsed(lastUpdate, -60) // Within last hour
    )

    return recentCompletions.length > 0 || this.hasTimeElapsed(lastUpdate, 60)
  }

  private shouldCheckGoalProgress(
    context: LearningContext, 
    state: CurriculumDirectorState
  ): boolean {
    // Check goal progress when modules are completed
    return context.eventHistory.some(e => e.eventType === 'module_completed')
  }

  private shouldUpdateDifficulty(
    context: LearningContext, 
    state: CurriculumDirectorState
  ): boolean {
    // Update difficulty based on recent performance
    const recentAssessments = context.recentAssessments.slice(0, 5)
    if (recentAssessments.length < 3) return false

    const averageScore = recentAssessments.reduce((sum, a) => sum + a.score, 0) / recentAssessments.length
    
    // Adjust if performance is consistently high or low
    return averageScore > 90 || averageScore < 70
  }

  // =============================================================================
  // Action Implementations
  // =============================================================================

  private async generateInitialCurriculum(context: LearningContext): Promise<AgentAction> {
    // For MVP, we'll use the existing curriculum but provide smart ordering
    const availableModules = context.availableModules.filter(m => m.status === 'not_started')
    const completedModuleIds = this.getCompletedModuleIds(context)
    
    // Filter modules by prerequisites and create learning path
    const eligibleModules = availableModules.filter(module => 
      this.arePrerequisitesMet(module.prerequisites, completedModuleIds)
    )

    // Sort by difficulty and user preferences
    const orderedModules = this.orderModulesByOptimalPath(eligibleModules, context)
    
    const curriculumData = {
      recommendedPath: orderedModules.map(m => m.id),
      estimatedTimeline: this.calculateTimeline(orderedModules, context),
      focusAreas: [context.userProfile.currentFocus],
      adaptedFor: {
        learningStyle: context.userProfile.learningStyle,
        hoursPerDay: context.userProfile.hoursPerDay,
        background: context.userProfile.background
      }
    }

    return this.createHighPriorityAction('update_curriculum', curriculumData)
  }

  private async adaptCurriculum(context: LearningContext): Promise<AgentAction[]> {
    const actions: AgentAction[] = []
    const recentPerformance = this.analyzeRecentPerformance(context)
    
    // Adjust difficulty if needed
    if (recentPerformance.averageScore > 90) {
      actions.push(this.createAction('log_event', {
        message: 'Recommending difficulty increase due to high performance',
        data: { averageScore: recentPerformance.averageScore }
      }, 6))
    } else if (recentPerformance.averageScore < 70) {
      actions.push(this.createAction('log_event', {
        message: 'Recommending additional review due to low performance',
        data: { averageScore: recentPerformance.averageScore }
      }, 8))
    }

    // Suggest timeline adjustments
    const currentVelocity = this.calculateLearningVelocity(context)
    if (currentVelocity > 0) {
      const timelineAdjustment = this.calculateTimelineAdjustment(currentVelocity, context)
      if (timelineAdjustment.shouldAdjust) {
        actions.push(this.createAction('update_curriculum', timelineAdjustment, 7))
      }
    }

    return actions
  }

  private async updateRecommendations(context: LearningContext): Promise<AgentAction> {
    const completedModuleIds = this.getCompletedModuleIds(context)
    const inProgressModuleIds = this.getInProgressModuleIds(context)
    
    // Find next recommended modules
    const recommendations = this.generateModuleRecommendations(
      context.availableModules,
      completedModuleIds,
      inProgressModuleIds,
      context.learningGoals,
      context.userProfile
    )

    // Update internal state
    const state = this.state as CurriculumDirectorState
    state.currentRecommendations = recommendations
    state.lastTimelineAdjustment = new Date().toISOString()

    return this.createAction('recommend_module', {
      recommendations: recommendations.slice(0, 3), // Top 3 recommendations
      reasoning: this.generateRecommendationReasoning(recommendations, context)
    }, 7)
  }

  private async checkGoalProgress(context: LearningContext): Promise<AgentAction[]> {
    const actions: AgentAction[] = []
    
    for (const goal of context.learningGoals) {
      const progress = this.calculateGoalProgress(goal, context)
      
      if (progress.completionPercentage > goal.progressPercentage + 10) {
        // Goal made significant progress
        actions.push(this.createAction('log_event', {
          message: `Significant progress on goal: ${goal.title}`,
          data: { 
            goalId: goal.id, 
            oldProgress: goal.progressPercentage,
            newProgress: progress.completionPercentage
          }
        }, 6))
      }
      
      if (progress.isAtRisk && goal.targetDate) {
        // Goal is at risk of not being completed on time
        actions.push(this.createAction('log_event', {
          message: `Goal at risk: ${goal.title}`,
          data: { 
            goalId: goal.id, 
            targetDate: goal.targetDate,
            currentProgress: progress.completionPercentage
          }
        }, 8))
      }
    }

    return actions
  }

  private async updateDifficultyProgression(context: LearningContext): Promise<AgentAction> {
    const recentPerformance = this.analyzeRecentPerformance(context)
    const state = this.state as CurriculumDirectorState
    
    let newDifficulty = state.difficultyProgression || 5
    
    if (recentPerformance.averageScore > 90) {
      newDifficulty = Math.min(10, newDifficulty + 1)
    } else if (recentPerformance.averageScore < 70) {
      newDifficulty = Math.max(1, newDifficulty - 1)
    }

    state.difficultyProgression = newDifficulty

    return this.createAction('log_event', {
      message: 'Updated difficulty progression',
      data: { 
        newDifficulty,
        basedOnScore: recentPerformance.averageScore,
        assessmentCount: recentPerformance.assessmentCount
      }
    }, 5)
  }

  // =============================================================================
  // Helper Methods
  // =============================================================================

  private orderModulesByOptimalPath(modules: Module[], context: LearningContext): Module[] {
    // Sort modules for optimal learning path
    return modules.sort((a, b) => {
      // 1. Prerequisites first
      if (a.prerequisites.length !== b.prerequisites.length) {
        return a.prerequisites.length - b.prerequisites.length
      }
      
      // 2. Difficulty progression
      if (a.difficultyLevel !== b.difficultyLevel) {
        return a.difficultyLevel - b.difficultyLevel
      }
      
      // 3. Estimated hours (shorter modules first for quick wins)
      return a.estimatedHours - b.estimatedHours
    })
  }

  private calculateTimeline(modules: Module[], context: LearningContext): any {
    const hoursPerDay = context.userProfile.hoursPerDay
    const totalHours = modules.reduce((sum, m) => sum + m.estimatedHours, 0)
    const estimatedDays = Math.ceil(totalHours / hoursPerDay)
    
    return {
      totalHours,
      estimatedDays,
      estimatedWeeks: Math.ceil(estimatedDays / 7),
      expectedCompletionDate: new Date(Date.now() + estimatedDays * 24 * 60 * 60 * 1000).toISOString()
    }
  }

  private analyzeRecentPerformance(context: LearningContext): any {
    const recentAssessments = context.recentAssessments.slice(0, 5)
    
    if (recentAssessments.length === 0) {
      return { averageScore: 0, assessmentCount: 0, trend: 'no_data' }
    }

    const averageScore = recentAssessments.reduce((sum, a) => sum + a.score, 0) / recentAssessments.length
    const scores = recentAssessments.map(a => a.score)
    
    // Calculate trend
    let trend = 'stable'
    if (scores.length >= 3) {
      const firstHalf = scores.slice(0, Math.floor(scores.length / 2))
      const secondHalf = scores.slice(Math.floor(scores.length / 2))
      const firstAvg = firstHalf.reduce((sum, s) => sum + s, 0) / firstHalf.length
      const secondAvg = secondHalf.reduce((sum, s) => sum + s, 0) / secondHalf.length
      
      if (secondAvg > firstAvg + 5) trend = 'improving'
      else if (secondAvg < firstAvg - 5) trend = 'declining'
    }

    return {
      averageScore,
      assessmentCount: recentAssessments.length,
      trend,
      weakAreas: this.identifyWeakAreas(recentAssessments),
      strengths: this.identifyStrengths(recentAssessments)
    }
  }

  private identifyWeakAreas(assessments: any[]): string[] {
    const weakAreas = new Set<string>()
    assessments.forEach(assessment => {
      assessment.weakAreas?.forEach((area: string) => weakAreas.add(area))
    })
    return Array.from(weakAreas)
  }

  private identifyStrengths(assessments: any[]): string[] {
    const strengths = new Set<string>()
    assessments.forEach(assessment => {
      assessment.strengths?.forEach((strength: string) => strengths.add(strength))
    })
    return Array.from(strengths)
  }

  private generateModuleRecommendations(
    modules: Module[],
    completedIds: number[],
    inProgressIds: number[],
    goals: LearningGoal[],
    userProfile: any
  ): ModuleRecommendation[] {
    const availableModules = modules.filter(m => 
      !completedIds.includes(m.id) && 
      !inProgressIds.includes(m.id) &&
      this.arePrerequisitesMet(m.prerequisites, completedIds)
    )

    return availableModules.map(module => ({
      moduleId: module.id,
      reason: this.generateRecommendationReason(module, goals, userProfile),
      priority: this.calculateModulePriority(module, goals, userProfile),
      estimatedStartDate: new Date().toISOString(),
      confidence: this.calculateRecommendationConfidence(module, completedIds, userProfile)
    })).sort((a, b) => b.priority - a.priority)
  }

  private generateRecommendationReason(module: Module, goals: LearningGoal[], userProfile: any): string {
    // Generate human-readable reason for recommendation
    const reasons = []
    
    if (module.prerequisites.length === 0) {
      reasons.push('foundational module')
    }
    
    if (module.difficultyLevel <= 3) {
      reasons.push('beginner-friendly')
    }
    
    const relatedGoals = goals.filter(g => g.targetModules.includes(module.id))
    if (relatedGoals.length > 0) {
      reasons.push(`contributes to ${relatedGoals.length} learning goal(s)`)
    }
    
    if (module.estimatedHours <= userProfile.hoursPerDay * 5) {
      reasons.push('fits current time commitment')
    }

    return reasons.join(', ') || 'next logical step in curriculum'
  }

  private calculateModulePriority(module: Module, goals: LearningGoal[], userProfile: any): number {
    let priority = 5 // Base priority
    
    // Higher priority for goal-related modules
    const relatedGoals = goals.filter(g => g.targetModules.includes(module.id))
    priority += relatedGoals.length * 2
    
    // Higher priority for high-priority goals
    const highPriorityGoals = relatedGoals.filter(g => g.priority >= 8)
    priority += highPriorityGoals.length * 2
    
    // Adjust for difficulty vs user background
    if (module.difficultyLevel <= 4 && userProfile.background.includes('beginner')) {
      priority += 1
    }
    
    // Lower priority for very long modules
    if (module.estimatedHours > userProfile.hoursPerDay * 10) {
      priority -= 2
    }

    return Math.max(1, Math.min(10, priority))
  }

  private calculateRecommendationConfidence(module: Module, completedIds: number[], userProfile: any): number {
    let confidence = 80 // Base confidence
    
    // Higher confidence if prerequisites are well completed
    const prerequisitesMet = this.arePrerequisitesMet(module.prerequisites, completedIds)
    if (prerequisitesMet) confidence += 10
    
    // Adjust for difficulty appropriateness
    const userExperience = completedIds.length
    const appropriateDifficulty = module.difficultyLevel <= (userExperience / 2) + 3
    if (appropriateDifficulty) confidence += 10
    
    return Math.max(50, Math.min(100, confidence))
  }

  private calculateGoalProgress(goal: LearningGoal, context: LearningContext): any {
    const targetModules = goal.targetModules
    const completedModules = targetModules.filter(id => 
      context.availableModules.find(m => m.id === id && m.status === 'completed')
    )
    
    const completionPercentage = (completedModules.length / targetModules.length) * 100
    
    // Check if goal is at risk based on target date
    let isAtRisk = false
    if (goal.targetDate) {
      const now = new Date()
      const target = new Date(goal.targetDate)
      const daysRemaining = (target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
      const remainingModules = targetModules.length - completedModules.length
      
      // Rough estimate: if more modules remaining than days available
      isAtRisk = remainingModules > daysRemaining && daysRemaining > 0
    }

    return {
      completionPercentage,
      completedModules: completedModules.length,
      totalModules: targetModules.length,
      isAtRisk
    }
  }

  private calculateTimelineAdjustment(velocity: number, context: LearningContext): any {
    const expectedVelocity = context.userProfile.hoursPerDay / 10
    const velocityRatio = velocity / expectedVelocity
    
    let shouldAdjust = false
    let adjustmentType = 'none'
    let adjustmentFactor = 1
    
    if (velocityRatio > 1.5) {
      shouldAdjust = true
      adjustmentType = 'accelerate'
      adjustmentFactor = 0.8 // Reduce estimated times by 20%
    } else if (velocityRatio < 0.5) {
      shouldAdjust = true
      adjustmentType = 'decelerate'
      adjustmentFactor = 1.3 // Increase estimated times by 30%
    }

    return {
      shouldAdjust,
      adjustmentType,
      adjustmentFactor,
      currentVelocity: velocity,
      expectedVelocity,
      reasoning: `Learning velocity is ${velocityRatio.toFixed(1)}x expected rate`
    }
  }

  private generateRecommendationReasoning(recommendations: ModuleRecommendation[], context: LearningContext): string {
    if (recommendations.length === 0) {
      return 'No new modules recommended at this time. Focus on completing current modules.'
    }

    const topRecommendation = recommendations[0]
    const reasons = [
      `Top recommendation: Module ${topRecommendation.moduleId}`,
      `Priority score: ${topRecommendation.priority}/10`,
      `Reason: ${topRecommendation.reason}`,
      `Confidence: ${topRecommendation.confidence}%`
    ]

    return reasons.join('. ')
  }

  private arraysEqual(a: any[], b: any[]): boolean {
    return a.length === b.length && a.every((val, index) => val === b[index])
  }

  // =============================================================================
  // State Management
  // =============================================================================

  protected async initializeDefaultState(sessionId: number): Promise<void> {
    await super.initializeDefaultState(sessionId)
    
    const defaultState: CurriculumDirectorState = {
      currentRecommendations: [],
      adaptationHistory: [],
      focusAreas: [],
      difficultyProgression: 5
    }

    this.state = { ...this.state, ...defaultState }
  }

  private async updateInternalState(context: LearningContext): Promise<void> {
    const state = this.state as CurriculumDirectorState
    
    // Update focus areas
    state.focusAreas = [context.userProfile.currentFocus]
    
    // Update last generation time if we made recommendations
    if (state.currentRecommendations.length > 0) {
      state.lastTimelineAdjustment = new Date().toISOString()
    }
  }
}