import { 
  AgentType, 
  AgentAction, 
  LearningContext, 
  LearningEvent,
  Assessment,
  QuizData,
  QuizQuestion,
  QuizResponse,
  Module
} from '../types/index.js'
import { BaseAgent } from './BaseAgent.js'
import { StateManager } from '../core/StateManager.js'

interface AssessmentCoachState {
  lastQuizGeneration?: string
  lastPerformanceAnalysis?: string
  performanceTrends: PerformanceTrend[]
  spacedRepetitionSchedule: SpacedRepetitionItem[]
  conceptMastery: Record<string, ConceptMasteryData>
  quizHistory: QuizHistoryItem[]
  adaptiveSettings: AdaptiveSettings
}

interface PerformanceTrend {
  concept: string
  scores: number[]
  timestamps: string[]
  trend: 'improving' | 'declining' | 'stable'
  confidence: number
}

interface SpacedRepetitionItem {
  concept: string
  moduleId: number
  lastReviewed: string
  nextReview: string
  repetitionLevel: number // 0-6 (Fibonacci-like intervals)
  masteryLevel: number // 0-100
}

interface ConceptMasteryData {
  concept: string
  masteryLevel: number // 0-100
  assessmentCount: number
  averageScore: number
  lastAssessed: string
  strengthAreas: string[]
  weaknessAreas: string[]
  improvementRate: number // Points per assessment
}

interface QuizHistoryItem {
  moduleId: number
  concept: string
  score: number
  difficulty: number
  timestamp: string
  timeSpent: number
  questionTypes: string[]
}

interface AdaptiveSettings {
  baseDifficulty: number // 1-10
  questionCount: number // Number of questions per quiz
  timeLimit: number // Seconds
  adaptationRate: number // How quickly to adjust difficulty
  masteryThreshold: number // Score needed to consider concept mastered
}

/**
 * Assessment Coach Agent
 * 
 * Responsibilities:
 * - Generate adaptive quizzes based on module content
 * - Analyze performance patterns and learning trends
 * - Implement spaced repetition for long-term retention
 * - Identify knowledge gaps and strengths
 * - Provide detailed feedback and recommendations
 * - Coordinate with Tutor and Curriculum Director agents
 */
export class AssessmentCoachAgent extends BaseAgent {
  readonly type: AgentType = 'assessment_coach'
  
  constructor(stateManager: StateManager) {
    super(stateManager)
  }

  protected getAgentName(): string {
    return 'Assessment Coach'
  }

  // =============================================================================
  // Main Processing Logic
  // =============================================================================

  async processContext(context: LearningContext): Promise<AgentAction[]> {
    try {
      await this.loadState(context.sessionId)
      
      const actions: AgentAction[] = []
      const state = this.state as AssessmentCoachState

      // 1. Check if module needs initial assessment
      if (this.shouldGenerateQuiz(context, state)) {
        const quizAction = await this.generateQuiz(context)
        actions.push(quizAction)
        await this.logInfo(context.sessionId, 'quiz_generated', {
          module: context.currentModule?.moduleName,
          difficulty: state.adaptiveSettings.baseDifficulty
        })
      }

      // 2. Analyze recent performance if new assessment data exists
      if (this.shouldAnalyzePerformance(context, state)) {
        const analysisActions = await this.analyzePerformance(context)
        actions.push(...analysisActions)
        await this.logInfo(context.sessionId, 'performance_analyzed', {
          assessmentCount: context.recentAssessments.length
        })
      }

      // 3. Check spaced repetition schedule
      if (this.shouldScheduleReview(context, state)) {
        const reviewActions = await this.scheduleSpacedRepetition(context)
        actions.push(...reviewActions)
      }

      // 4. Update concept mastery levels
      if (this.shouldUpdateMastery(context, state)) {
        const masteryAction = await this.updateConceptMastery(context)
        actions.push(masteryAction)
      }

      // 5. Provide performance feedback and recommendations
      if (this.shouldProvideFeedback(context, state)) {
        const feedbackAction = await this.generatePerformanceFeedback(context)
        actions.push(feedbackAction)
      }

      // 6. Adapt difficulty settings based on performance
      if (this.shouldAdaptDifficulty(context, state)) {
        const adaptationAction = await this.adaptDifficultySettings(context)
        actions.push(adaptationAction)
      }

      // Update internal state
      await this.updateInternalState(context)

      return actions.sort((a, b) => b.priority - a.priority)
    } catch (error) {
      return await this.handleError(context.sessionId, 'processContext', error)
    }
  }

  // =============================================================================
  // Decision Logic
  // =============================================================================

  private shouldGenerateQuiz(
    context: LearningContext, 
    state: AssessmentCoachState
  ): boolean {
    // Generate quiz if we have a current module and haven't assessed it recently
    if (!context.currentModule) return false
    
    const moduleId = context.currentModule.id
    const lastQuiz = state.quizHistory.find(q => 
      q.moduleId === moduleId && 
      this.hasTimeElapsed(q.timestamp, -120) // Within last 2 hours
    )
    
    if (lastQuiz) return false // Too recent
    
    // Check if module needs assessment based on user progress
    const moduleProgress = context.sessionState.progressInModule || 0
    return moduleProgress > 70 // Assess when 70% through module
  }

  private shouldAnalyzePerformance(
    context: LearningContext, 
    state: AssessmentCoachState
  ): boolean {
    // Analyze if we have new assessment data
    const lastAnalysis = state.lastPerformanceAnalysis
    if (!lastAnalysis) return context.recentAssessments.length > 0
    
    // Check for new assessments since last analysis
    const newAssessments = context.recentAssessments.filter(a => 
      new Date(a.createdAt) > new Date(lastAnalysis)
    )
    
    return newAssessments.length > 0
  }

  private shouldScheduleReview(
    context: LearningContext, 
    state: AssessmentCoachState
  ): boolean {
    // Check if any concepts are due for spaced repetition review
    const now = new Date()
    const dueReviews = state.spacedRepetitionSchedule.filter(item => 
      new Date(item.nextReview) <= now
    )
    
    return dueReviews.length > 0
  }

  private shouldUpdateMastery(
    context: LearningContext, 
    state: AssessmentCoachState
  ): boolean {
    // Update mastery levels when we have new assessment data
    return context.recentAssessments.some(a => 
      this.hasTimeElapsed(a.createdAt, -60) // Within last hour
    )
  }

  private shouldProvideFeedback(
    context: LearningContext, 
    state: AssessmentCoachState
  ): boolean {
    // Provide feedback after each assessment or when performance patterns emerge
    const recentAssessments = context.recentAssessments.filter(a => 
      this.hasTimeElapsed(a.createdAt, -30) // Within last 30 minutes
    )
    
    return recentAssessments.length > 0 || state.performanceTrends.some(t => t.trend !== 'stable')
  }

  private shouldAdaptDifficulty(
    context: LearningContext, 
    state: AssessmentCoachState
  ): boolean {
    // Adapt difficulty if we have enough data and clear performance trends
    const recentScores = context.recentAssessments.slice(0, 3).map(a => a.score)
    if (recentScores.length < 3) return false
    
    const averageScore = recentScores.reduce((sum, score) => sum + score, 0) / recentScores.length
    
    // Adapt if consistently too easy or too hard
    return averageScore > 90 || averageScore < 65
  }

  // =============================================================================
  // Action Implementations
  // =============================================================================

  private async generateQuiz(context: LearningContext): Promise<AgentAction> {
    const module = context.currentModule!
    const state = this.state as AssessmentCoachState
    
    // Generate quiz questions based on module content and adaptive settings
    const quizData = await this.createQuizQuestions(module, context, state.adaptiveSettings)
    
    // Record quiz generation
    state.quizHistory.push({
      moduleId: module.id,
      concept: module.moduleName,
      score: 0, // Will be updated when completed
      difficulty: state.adaptiveSettings.baseDifficulty,
      timestamp: new Date().toISOString(),
      timeSpent: 0,
      questionTypes: quizData.questions.map(q => q.type)
    })
    
    state.lastQuizGeneration = new Date().toISOString()

    return this.createHighPriorityAction('generate_quiz', {
      moduleId: module.id,
      moduleName: module.moduleName,
      quizData,
      adaptiveSettings: {
        difficulty: state.adaptiveSettings.baseDifficulty,
        questionCount: quizData.questions.length,
        timeLimit: quizData.timeLimit,
        masteryThreshold: state.adaptiveSettings.masteryThreshold
      },
      instructions: this.generateQuizInstructions(module, state.adaptiveSettings)
    })
  }

  private async analyzePerformance(context: LearningContext): Promise<AgentAction[]> {
    const actions: AgentAction[] = []
    const state = this.state as AssessmentCoachState
    const recentAssessments = context.recentAssessments.slice(0, 5)
    
    // Analyze performance trends
    const trends = this.calculatePerformanceTrends(recentAssessments, state.performanceTrends)
    state.performanceTrends = trends
    
    // Identify knowledge gaps
    const knowledgeGaps = this.identifyKnowledgeGaps(recentAssessments)
    
    // Calculate overall performance metrics
    const performanceMetrics = this.calculatePerformanceMetrics(recentAssessments, context)
    
    actions.push(this.createAction('log_event', {
      message: 'Performance analysis completed',
      data: {
        trendsAnalyzed: trends.length,
        knowledgeGaps: knowledgeGaps.length,
        overallPerformance: performanceMetrics.averageScore,
        improvementAreas: knowledgeGaps.slice(0, 3)
      }
    }, 6))

    // Generate specific recommendations based on analysis
    if (knowledgeGaps.length > 0) {
      actions.push(this.createAction('recommend_module', {
        type: 'remediation',
        concepts: knowledgeGaps,
        reasoning: 'Performance analysis identified knowledge gaps requiring additional focus',
        suggestedActions: this.generateRemediationSuggestions(knowledgeGaps)
      }, 8))
    }

    state.lastPerformanceAnalysis = new Date().toISOString()
    
    return actions
  }

  private async scheduleSpacedRepetition(context: LearningContext): Promise<AgentAction[]> {
    const actions: AgentAction[] = []
    const state = this.state as AssessmentCoachState
    
    // Find concepts due for review
    const now = new Date()
    const dueReviews = state.spacedRepetitionSchedule.filter(item => 
      new Date(item.nextReview) <= now
    )
    
    // Schedule review quizzes for due concepts
    for (const reviewItem of dueReviews.slice(0, 3)) { // Limit to 3 reviews per session
      const reviewQuiz = await this.createReviewQuiz(reviewItem, context)
      
      actions.push(this.createAction('generate_quiz', {
        type: 'spaced_repetition_review',
        concept: reviewItem.concept,
        moduleId: reviewItem.moduleId,
        reviewLevel: reviewItem.repetitionLevel,
        quizData: reviewQuiz,
        instructions: `Review quiz for ${reviewItem.concept} (repetition level ${reviewItem.repetitionLevel})`
      }, 7))
      
      // Update next review date
      reviewItem.nextReview = this.calculateNextReviewDate(reviewItem.repetitionLevel).toISOString()
    }
    
    return actions
  }

  private async updateConceptMastery(context: LearningContext): Promise<AgentAction> {
    const state = this.state as AssessmentCoachState
    const recentAssessments = context.recentAssessments.slice(0, 3)
    
    // Update mastery data for assessed concepts
    recentAssessments.forEach(assessment => {
      const moduleKey = `module_${assessment.moduleId}`
      
      if (!state.conceptMastery[moduleKey]) {
        state.conceptMastery[moduleKey] = {
          concept: moduleKey,
          masteryLevel: 0,
          assessmentCount: 0,
          averageScore: 0,
          lastAssessed: '',
          strengthAreas: [],
          weaknessAreas: [],
          improvementRate: 0
        }
      }
      
      const mastery = state.conceptMastery[moduleKey]
      
      // Update mastery level (weighted average with recent performance)
      const weight = 0.3 // Weight for new assessment
      mastery.masteryLevel = (mastery.masteryLevel * (1 - weight)) + (assessment.score * weight)
      
      // Update statistics
      mastery.assessmentCount++
      mastery.averageScore = ((mastery.averageScore * (mastery.assessmentCount - 1)) + assessment.score) / mastery.assessmentCount
      mastery.lastAssessed = assessment.createdAt.toISOString()
      
      // Update strength and weakness areas
      mastery.strengthAreas = [...new Set([...mastery.strengthAreas, ...assessment.strengths])]
      mastery.weaknessAreas = [...new Set([...mastery.weaknessAreas, ...assessment.weakAreas])]
      
      // Calculate improvement rate
      if (mastery.assessmentCount > 1) {
        const previousScore = mastery.averageScore - ((assessment.score - mastery.averageScore) / (mastery.assessmentCount - 1))
        mastery.improvementRate = assessment.score - previousScore
      }
    })
    
    // Calculate overall mastery statistics
    const masteryLevels = Object.values(state.conceptMastery).map(m => m.masteryLevel)
    const averageMastery = masteryLevels.length > 0 ? 
      masteryLevels.reduce((sum, level) => sum + level, 0) / masteryLevels.length : 0
    
    return this.createAction('log_event', {
      message: 'Concept mastery levels updated',
      data: {
        conceptsTracked: Object.keys(state.conceptMastery).length,
        averageMastery: Math.round(averageMastery),
        masteredConcepts: masteryLevels.filter(level => level >= state.adaptiveSettings.masteryThreshold).length,
        assessmentCount: recentAssessments.length
      }
    }, 5)
  }

  private async generatePerformanceFeedback(context: LearningContext): Promise<AgentAction> {
    const state = this.state as AssessmentCoachState
    const recentAssessments = context.recentAssessments.slice(0, 3)
    
    if (recentAssessments.length === 0) {
      return this.createLowPriorityAction('log_event', { 
        message: 'No recent assessments for feedback generation' 
      })
    }
    
    // Generate comprehensive feedback
    const feedback = this.generateDetailedFeedback(recentAssessments, state, context)
    
    return this.createAction('provide_explanation', {
      type: 'performance_feedback',
      feedback: feedback.summary,
      strengths: feedback.strengths,
      improvementAreas: feedback.weaknesses,
      recommendations: feedback.recommendations,
      progressMetrics: feedback.metrics,
      encouragement: feedback.encouragement,
      nextSteps: feedback.nextSteps
    }, 7)
  }

  private async adaptDifficultySettings(context: LearningContext): Promise<AgentAction> {
    const state = this.state as AssessmentCoachState
    const recentScores = context.recentAssessments.slice(0, 5).map(a => a.score)
    
    if (recentScores.length < 3) {
      return this.createLowPriorityAction('log_event', { 
        message: 'Insufficient data for difficulty adaptation' 
      })
    }
    
    const averageScore = recentScores.reduce((sum, score) => sum + score, 0) / recentScores.length
    const currentDifficulty = state.adaptiveSettings.baseDifficulty
    let newDifficulty = currentDifficulty
    let adaptationReason = ''
    
    // Adapt difficulty based on performance
    if (averageScore > 90) {
      newDifficulty = Math.min(10, currentDifficulty + 1)
      adaptationReason = 'Increasing difficulty due to high performance'
    } else if (averageScore < 65) {
      newDifficulty = Math.max(1, currentDifficulty - 1)
      adaptationReason = 'Decreasing difficulty due to challenging performance'
    } else if (averageScore > 85) {
      // Slight increase for good performance
      newDifficulty = Math.min(10, currentDifficulty + 0.5)
      adaptationReason = 'Slightly increasing difficulty for optimal challenge'
    }
    
    // Update settings if change is needed
    if (newDifficulty !== currentDifficulty) {
      state.adaptiveSettings.baseDifficulty = newDifficulty
      
      // Also adjust question count and time limit
      if (newDifficulty > currentDifficulty) {
        state.adaptiveSettings.questionCount = Math.min(15, state.adaptiveSettings.questionCount + 1)
        state.adaptiveSettings.timeLimit = Math.max(300, state.adaptiveSettings.timeLimit - 30)
      } else {
        state.adaptiveSettings.questionCount = Math.max(5, state.adaptiveSettings.questionCount - 1)
        state.adaptiveSettings.timeLimit = Math.min(900, state.adaptiveSettings.timeLimit + 60)
      }
    }
    
    return this.createAction('log_event', {
      message: 'Adaptive difficulty settings updated',
      data: {
        previousDifficulty: currentDifficulty,
        newDifficulty,
        averageScore: Math.round(averageScore),
        adaptationReason,
        newSettings: state.adaptiveSettings
      }
    }, 6)
  }

  // =============================================================================
  // Content Generation (MVP Implementation)
  // =============================================================================

  private async createQuizQuestions(
    module: Module, 
    context: LearningContext, 
    settings: AdaptiveSettings
  ): Promise<QuizData> {
    // For MVP: Generate quiz questions based on module content
    // Future: This will be replaced with BAML calls
    
    const questions = this.generateQuestionsForModule(module, settings)
    
    return {
      questions,
      timeLimit: settings.timeLimit,
      instructions: `Assessment for ${module.moduleName}. Answer all questions to the best of your ability.`
    }
  }

  private generateQuestionsForModule(module: Module, settings: AdaptiveSettings): QuizQuestion[] {
    const questions: QuizQuestion[] = []
    const difficulty = settings.baseDifficulty
    const questionCount = settings.questionCount
    
    // Question templates by module
    const questionTemplates = this.getQuestionTemplates(module.moduleName, difficulty)
    
    // Generate mix of question types
    const questionTypes = this.determineQuestionTypes(questionCount, difficulty)
    
    questionTypes.forEach((type, index) => {
      const template = questionTemplates[type] || questionTemplates['multiple_choice']
      questions.push({
        id: `q${index + 1}`,
        type: type as any,
        question: template.question,
        options: template.options,
        correctAnswer: template.correctAnswer,
        explanation: template.explanation,
        difficulty,
        concept: module.moduleName
      })
    })
    
    return questions
  }

  private getQuestionTemplates(moduleName: string, difficulty: number): Record<string, any> {
    // MVP: Template-based questions
    // Future: BAML-generated questions
    
    const templates = {
      'Introduction to Machine Learning': {
        multiple_choice: {
          question: 'What is the primary goal of machine learning?',
          options: [
            'To replace human programmers',
            'To enable computers to learn patterns from data without explicit programming',
            'To create artificial consciousness',
            'To automate all business processes'
          ],
          correctAnswer: 'To enable computers to learn patterns from data without explicit programming',
          explanation: 'Machine learning focuses on algorithms that can learn and make predictions from data without being explicitly programmed for each specific task.'
        },
        true_false: {
          question: 'Machine learning algorithms always require labeled training data.',
          options: ['True', 'False'],
          correctAnswer: 'False',
          explanation: 'Unsupervised learning algorithms can work with unlabeled data to find patterns and structures.'
        }
      },
      'Linear Regression': {
        multiple_choice: {
          question: 'In linear regression, what does the slope of the line represent?',
          options: [
            'The prediction error',
            'The rate of change in the dependent variable per unit change in the independent variable',
            'The correlation coefficient',
            'The intercept value'
          ],
          correctAnswer: 'The rate of change in the dependent variable per unit change in the independent variable',
          explanation: 'The slope indicates how much the output variable changes for each unit increase in the input variable.'
        },
        short_answer: {
          question: 'Explain the difference between simple and multiple linear regression.',
          correctAnswer: 'Simple linear regression uses one independent variable, while multiple linear regression uses two or more independent variables to predict the dependent variable.',
          explanation: 'Simple regression: y = mx + b. Multiple regression: y = b₀ + b₁x₁ + b₂x₂ + ... + bₙxₙ'
        }
      }
    }
    
    return templates[moduleName as keyof typeof templates] || templates['Introduction to Machine Learning']
  }

  private determineQuestionTypes(questionCount: number, difficulty: number): string[] {
    const types = []
    
    // Base question distribution
    const multipleChoiceCount = Math.ceil(questionCount * 0.6)
    const trueFalseCount = Math.ceil(questionCount * 0.2)
    const shortAnswerCount = questionCount - multipleChoiceCount - trueFalseCount
    
    // Add questions based on difficulty
    for (let i = 0; i < multipleChoiceCount; i++) types.push('multiple_choice')
    for (let i = 0; i < trueFalseCount; i++) types.push('true_false')
    
    // Add more complex questions for higher difficulty
    if (difficulty >= 5) {
      for (let i = 0; i < shortAnswerCount; i++) types.push('short_answer')
    }
    
    if (difficulty >= 7) {
      types.push('code_completion')
    }
    
    return types.slice(0, questionCount)
  }

  private async createReviewQuiz(reviewItem: SpacedRepetitionItem, context: LearningContext): Promise<QuizData> {
    // Create shorter quiz for spaced repetition review
    const questionCount = Math.max(3, Math.floor(reviewItem.repetitionLevel + 2))
    const timeLimit = questionCount * 60 // 1 minute per question
    
    const module = context.availableModules.find(m => m.id === reviewItem.moduleId)
    if (!module) {
      throw new Error(`Module ${reviewItem.moduleId} not found for review quiz`)
    }
    
    const settings: AdaptiveSettings = {
      baseDifficulty: Math.max(1, Math.floor(reviewItem.masteryLevel / 15)),
      questionCount,
      timeLimit,
      adaptationRate: 0.1,
      masteryThreshold: 80
    }
    
    return await this.createQuizQuestions(module, context, settings)
  }

  // =============================================================================
  // Analysis and Calculation Methods
  // =============================================================================

  private calculatePerformanceTrends(
    recentAssessments: Assessment[], 
    existingTrends: PerformanceTrend[]
  ): PerformanceTrend[] {
    const trends: PerformanceTrend[] = []
    
    // Group assessments by concept/module
    const assessmentsByModule = new Map<number, Assessment[]>()
    recentAssessments.forEach(assessment => {
      const moduleAssessments = assessmentsByModule.get(assessment.moduleId) || []
      moduleAssessments.push(assessment)
      assessmentsByModule.set(assessment.moduleId, moduleAssessments)
    })
    
    // Calculate trends for each module
    assessmentsByModule.forEach((assessments, moduleId) => {
      if (assessments.length < 2) return
      
      const scores = assessments.map(a => a.score)
      const timestamps = assessments.map(a => a.createdAt.toISOString())
      
      // Calculate trend
      const firstHalf = scores.slice(0, Math.floor(scores.length / 2))
      const secondHalf = scores.slice(Math.floor(scores.length / 2))
      
      const firstAvg = firstHalf.reduce((sum, s) => sum + s, 0) / firstHalf.length
      const secondAvg = secondHalf.reduce((sum, s) => sum + s, 0) / secondHalf.length
      
      let trend: 'improving' | 'declining' | 'stable' = 'stable'
      if (secondAvg > firstAvg + 5) trend = 'improving'
      else if (secondAvg < firstAvg - 5) trend = 'declining'
      
      // Calculate confidence based on data points and variance
      const variance = this.calculateVariance(scores)
      const confidence = Math.max(50, Math.min(100, 100 - variance))
      
      trends.push({
        concept: `module_${moduleId}`,
        scores,
        timestamps,
        trend,
        confidence
      })
    })
    
    return trends
  }

  private identifyKnowledgeGaps(assessments: Assessment[]): string[] {
    const weakConcepts = new Map<string, number>()
    
    assessments.forEach(assessment => {
      assessment.weakAreas.forEach(weakness => {
        weakConcepts.set(weakness, (weakConcepts.get(weakness) || 0) + 1)
      })
    })
    
    // Return concepts that appear as weaknesses in multiple assessments
    return Array.from(weakConcepts.entries())
      .filter(([_, count]) => count >= 2)
      .sort((a, b) => b[1] - a[1])
      .map(([concept, _]) => concept)
  }

  private calculatePerformanceMetrics(assessments: Assessment[], context: LearningContext): any {
    if (assessments.length === 0) {
      return {
        averageScore: 0,
        averageTime: 0,
        completionRate: 0,
        improvementRate: 0
      }
    }
    
    const scores = assessments.map(a => a.score)
    const times = assessments.map(a => a.completionTime)
    
    const averageScore = scores.reduce((sum, score) => sum + score, 0) / scores.length
    const averageTime = times.reduce((sum, time) => sum + time, 0) / times.length
    
    // Calculate improvement rate (slope of scores over time)
    let improvementRate = 0
    if (scores.length >= 2) {
      const firstScore = scores[0]
      const lastScore = scores[scores.length - 1]
      improvementRate = (lastScore - firstScore) / (scores.length - 1)
    }
    
    return {
      averageScore: Math.round(averageScore),
      averageTime: Math.round(averageTime),
      completionRate: 100, // All provided assessments are completed
      improvementRate: Math.round(improvementRate * 10) / 10
    }
  }

  private generateRemediationSuggestions(knowledgeGaps: string[]): string[] {
    return knowledgeGaps.map(gap => 
      `Review and practice ${gap} with additional examples and exercises`
    )
  }

  private generateDetailedFeedback(
    assessments: Assessment[], 
    state: AssessmentCoachState, 
    context: LearningContext
  ): any {
    const metrics = this.calculatePerformanceMetrics(assessments, context)
    const recentAssessment = assessments[0]
    
    // Generate personalized feedback
    let summary = ''
    let encouragement = ''
    
    if (metrics.averageScore >= 85) {
      summary = 'Excellent performance! You\'re demonstrating strong understanding of the concepts.'
      encouragement = 'Keep up the great work! You\'re ready for more challenging material.'
    } else if (metrics.averageScore >= 70) {
      summary = 'Good progress! You\'re on the right track with solid foundational understanding.'
      encouragement = 'With a bit more practice, you\'ll master these concepts completely.'
    } else {
      summary = 'You\'re making progress, but there are some concepts that need more attention.'
      encouragement = 'Don\'t worry - learning takes time. Focus on the fundamentals and you\'ll improve.'
    }
    
    // Extract strengths and weaknesses
    const allStrengths = new Set<string>()
    const allWeaknesses = new Set<string>()
    
    assessments.forEach(assessment => {
      assessment.strengths.forEach(strength => allStrengths.add(strength))
      assessment.weakAreas.forEach(weakness => allWeaknesses.add(weakness))
    })
    
    return {
      summary,
      strengths: Array.from(allStrengths),
      weaknesses: Array.from(allWeaknesses),
      recommendations: this.generateRemediationSuggestions(Array.from(allWeaknesses)),
      metrics,
      encouragement,
      nextSteps: this.generateNextSteps(metrics, Array.from(allWeaknesses))
    }
  }

  private generateNextSteps(metrics: any, weaknesses: string[]): string[] {
    const steps = []
    
    if (weaknesses.length > 0) {
      steps.push(`Focus on improving understanding of: ${weaknesses.slice(0, 2).join(', ')}`)
    }
    
    if (metrics.averageScore < 70) {
      steps.push('Review fundamental concepts before proceeding to advanced topics')
    } else if (metrics.averageScore >= 85) {
      steps.push('Ready to advance to the next module or increase difficulty level')
    }
    
    if (metrics.averageTime > 600) { // More than 10 minutes
      steps.push('Practice solving problems more efficiently to improve speed')
    }
    
    return steps
  }

  private calculateVariance(scores: number[]): number {
    if (scores.length < 2) return 0
    
    const mean = scores.reduce((sum, score) => sum + score, 0) / scores.length
    const squaredDiffs = scores.map(score => Math.pow(score - mean, 2))
    return squaredDiffs.reduce((sum, diff) => sum + diff, 0) / scores.length
  }

  private calculateNextReviewDate(repetitionLevel: number): Date {
    // Spaced repetition intervals (in days): 1, 2, 4, 8, 16, 32, 64
    const intervals = [1, 2, 4, 8, 16, 32, 64]
    const interval = intervals[Math.min(repetitionLevel, intervals.length - 1)]
    
    const nextReview = new Date()
    nextReview.setDate(nextReview.getDate() + interval)
    return nextReview
  }

  private generateQuizInstructions(module: Module, settings: AdaptiveSettings): string {
    return `
Assessment for ${module.moduleName}

Instructions:
• This quiz contains ${settings.questionCount} questions
• You have ${Math.floor(settings.timeLimit / 60)} minutes to complete it
• Read each question carefully before answering
• You need ${settings.masteryThreshold}% to demonstrate mastery
• Take your time and think through each answer

Good luck!
    `.trim()
  }

  // =============================================================================
  // State Management
  // =============================================================================

  protected async initializeDefaultState(sessionId: number): Promise<void> {
    await super.initializeDefaultState(sessionId)
    
    const defaultState: AssessmentCoachState = {
      performanceTrends: [],
      spacedRepetitionSchedule: [],
      conceptMastery: {},
      quizHistory: [],
      adaptiveSettings: {
        baseDifficulty: 5,
        questionCount: 8,
        timeLimit: 480, // 8 minutes
        adaptationRate: 0.2,
        masteryThreshold: 80
      }
    }

    this.state = { ...this.state, ...defaultState }
  }

  private async updateInternalState(context: LearningContext): Promise<void> {
    const state = this.state as AssessmentCoachState
    
    // Update spaced repetition schedule for completed modules
    const completedModules = context.availableModules.filter(m => m.status === 'completed')
    
    completedModules.forEach(module => {
      const existingItem = state.spacedRepetitionSchedule.find(item => item.moduleId === module.id)
      
      if (!existingItem) {
        // Add new item to spaced repetition schedule
        state.spacedRepetitionSchedule.push({
          concept: module.moduleName,
          moduleId: module.id,
          lastReviewed: new Date().toISOString(),
          nextReview: this.calculateNextReviewDate(0).toISOString(),
          repetitionLevel: 0,
          masteryLevel: 70 // Start with assumption of basic mastery
        })
      }
    })
  }

  // =============================================================================
  // Public Interface for Other Agents
  // =============================================================================

  async getConceptMastery(concept: string): Promise<number> {
    const state = this.state as AssessmentCoachState
    return state.conceptMastery[concept]?.masteryLevel || 0
  }

  async scheduleConceptReview(concept: string, moduleId: number): Promise<void> {
    const state = this.state as AssessmentCoachState
    
    const existingItem = state.spacedRepetitionSchedule.find(item => 
      item.concept === concept && item.moduleId === moduleId
    )
    
    if (existingItem) {
      // Reset review schedule for struggling concept
      existingItem.repetitionLevel = Math.max(0, existingItem.repetitionLevel - 1)
      existingItem.nextReview = this.calculateNextReviewDate(existingItem.repetitionLevel).toISOString()
    }
  }

  async getPerformanceTrends(): Promise<PerformanceTrend[]> {
    const state = this.state as AssessmentCoachState
    return state.performanceTrends
  }

  async updateDifficultyPreference(newDifficulty: number): Promise<void> {
    const state = this.state as AssessmentCoachState
    state.adaptiveSettings.baseDifficulty = Math.max(1, Math.min(10, newDifficulty))
  }
}