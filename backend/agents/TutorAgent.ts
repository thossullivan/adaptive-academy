import { 
  AgentType, 
  AgentAction, 
  LearningContext, 
  LearningEvent,
  Explanation,
  TeachingContext,
  Module
} from '../types/index.js'
import { BaseAgent } from './BaseAgent.js'
import { StateManager } from '../core/StateManager.js'

interface TutorAgentState {
  currentConcept?: string
  explanationHistory: ExplanationRecord[]
  userUnderstanding: Record<string, number> // concept -> understanding level (0-100)
  preferredExplanationStyle: string
  lastInteraction?: string
  sessionConcepts: string[]
  adaptationLevel: number // How much we've adapted to this user
}

interface ExplanationRecord {
  concept: string
  explanation: string
  timestamp: string
  userFeedback?: 'helpful' | 'confusing' | 'too_easy' | 'too_hard'
  followUpQuestions: string[]
  analogiesUsed: string[]
}

interface ConceptExplanationRequest {
  concept: string
  context: LearningContext
  requestType: 'initial' | 'clarification' | 'example' | 'analogy'
  userQuestion?: string
}

/**
 * Tutor Agent
 * 
 * Responsibilities:
 * - Generate concept explanations tailored to user's learning style
 * - Provide physics analogies for AI/ML concepts
 * - Answer user questions during study sessions
 * - Adapt teaching approach based on user understanding
 * - Track concept mastery and provide targeted help
 */
export class TutorAgent extends BaseAgent {
  readonly type: AgentType = 'tutor'
  
  constructor(stateManager: StateManager) {
    super(stateManager)
  }

  protected getAgentName(): string {
    return 'Tutor'
  }

  // =============================================================================
  // Main Processing Logic
  // =============================================================================

  async processContext(context: LearningContext): Promise<AgentAction[]> {
    try {
      await this.loadState(context.sessionId)
      
      const actions: AgentAction[] = []
      const state = this.state as TutorAgentState

      // 1. Check if user needs concept explanation for current module
      if (this.shouldProvideConceptExplanation(context, state)) {
        const explanationAction = await this.generateConceptExplanation(context)
        actions.push(explanationAction)
        await this.logInfo(context.sessionId, 'concept_explained', {
          concept: state.currentConcept,
          module: context.currentModule?.moduleName
        })
      }

      // 2. Check if user asked a question that needs answering
      if (this.shouldAnswerUserQuestion(context, state)) {
        const answerAction = await this.answerUserQuestion(context)
        actions.push(answerAction)
      }

      // 3. Check if we should provide additional examples or analogies
      if (this.shouldProvideAdditionalHelp(context, state)) {
        const helpAction = await this.provideAdditionalHelp(context)
        actions.push(helpAction)
      }

      // 4. Check if we should adapt teaching style based on recent performance
      if (this.shouldAdaptTeachingStyle(context, state)) {
        const adaptationAction = await this.adaptTeachingStyle(context)
        actions.push(adaptationAction)
      }

      // 5. Update concept understanding based on recent assessments
      if (this.shouldUpdateUnderstanding(context, state)) {
        const understandingAction = await this.updateConceptUnderstanding(context)
        actions.push(understandingAction)
      }

      // Update our state with latest teaching session
      await this.updateInternalState(context)

      return actions.sort((a, b) => b.priority - a.priority)
    } catch (error) {
      return await this.handleError(context.sessionId, 'processContext', error)
    }
  }

  // =============================================================================
  // Decision Logic
  // =============================================================================

  private shouldProvideConceptExplanation(
    context: LearningContext, 
    state: TutorAgentState
  ): boolean {
    // Provide explanation if we have a current module and haven't explained it recently
    if (!context.currentModule) return false
    
    const moduleKey = `module_${context.currentModule.id}`
    const lastExplanation = state.explanationHistory.find(e => 
      e.concept.includes(context.currentModule!.moduleName)
    )
    
    if (!lastExplanation) return true
    
    // Re-explain if it's been a while or user understanding is low
    const timeSinceExplanation = this.hasTimeElapsed(lastExplanation.timestamp, 60)
    const understandingLevel = state.userUnderstanding[moduleKey] || 0
    
    return timeSinceExplanation || understandingLevel < 70
  }

  private shouldAnswerUserQuestion(
    context: LearningContext, 
    state: TutorAgentState
  ): boolean {
    // Check if there are recent question events in the event history
    const recentQuestions = context.eventHistory.filter(e => 
      e.eventType === 'user_question' && 
      this.hasTimeElapsed(e.timestamp, -30) // Within last 30 minutes
    )
    
    return recentQuestions.length > 0
  }

  private shouldProvideAdditionalHelp(
    context: LearningContext, 
    state: TutorAgentState
  ): boolean {
    // Provide additional help if user is struggling
    const recentAssessments = context.recentAssessments.slice(0, 2)
    if (recentAssessments.length === 0) return false

    const averageScore = recentAssessments.reduce((sum, a) => sum + a.score, 0) / recentAssessments.length
    
    // Offer help if recent performance is low
    return averageScore < 75
  }

  private shouldAdaptTeachingStyle(
    context: LearningContext, 
    state: TutorAgentState
  ): boolean {
    // Adapt if we have enough data and user preferences have evolved
    const explanationCount = state.explanationHistory.length
    if (explanationCount < 3) return false

    // Check if recent explanations haven't been effective
    const recentExplanations = state.explanationHistory.slice(-3)
    const ineffectiveExplanations = recentExplanations.filter(e => 
      e.userFeedback === 'confusing' || e.userFeedback === 'too_hard'
    )

    return ineffectiveExplanations.length >= 2
  }

  private shouldUpdateUnderstanding(
    context: LearningContext, 
    state: TutorAgentState
  ): boolean {
    // Update understanding when new assessment data is available
    const recentAssessments = context.recentAssessments.filter(a => 
      this.hasTimeElapsed(a.createdAt, -60) // Within last hour
    )
    
    return recentAssessments.length > 0
  }

  // =============================================================================
  // Action Implementations
  // =============================================================================

  private async generateConceptExplanation(context: LearningContext): Promise<AgentAction> {
    const module = context.currentModule!
    const state = this.state as TutorAgentState

    // For MVP: Generate explanation based on module and user preferences
    // Future: This will be a BAML call
    const explanation = await this.createExplanation({
      concept: module.moduleName,
      context,
      requestType: 'initial'
    })

    // Record the explanation
    state.explanationHistory.push({
      concept: module.moduleName,
      explanation: explanation.explanation,
      timestamp: new Date().toISOString(),
      followUpQuestions: explanation.followUpQuestions,
      analogiesUsed: explanation.analogies
    })

    // Set current concept
    state.currentConcept = module.moduleName

    return this.createHighPriorityAction('provide_explanation', {
      concept: module.moduleName,
      explanation: explanation.explanation,
      analogies: explanation.analogies,
      examples: explanation.examples,
      followUpQuestions: explanation.followUpQuestions,
      difficulty: explanation.difficultyLevel,
      adaptedFor: {
        learningStyle: context.userProfile.learningStyle,
        background: context.userProfile.background,
        explanationStyle: context.preferences.explanationStyle
      }
    })
  }

  private async answerUserQuestion(context: LearningContext): Promise<AgentAction> {
    // Find the most recent user question
    const questionEvent = context.eventHistory
      .filter(e => e.eventType === 'user_question')
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0]

    if (!questionEvent) {
      return this.createAction('log_event', { message: 'No user question found' }, 1)
    }

    const userQuestion = questionEvent.eventData.question || ''
    const relatedConcept = questionEvent.eventData.concept || context.currentModule?.moduleName || 'general'

    // Generate targeted answer
    const answer = await this.createExplanation({
      concept: relatedConcept,
      context,
      requestType: 'clarification',
      userQuestion
    })

    return this.createHighPriorityAction('provide_explanation', {
      type: 'question_answer',
      userQuestion,
      answer: answer.explanation,
      concept: relatedConcept,
      examples: answer.examples,
      relatedConcepts: answer.relatedConcepts
    })
  }

  private async provideAdditionalHelp(context: LearningContext): Promise<AgentAction> {
    const state = this.state as TutorAgentState
    const recentAssessments = context.recentAssessments.slice(0, 2)
    
    // Identify weak areas from recent assessments
    const weakConcepts = new Set<string>()
    recentAssessments.forEach(assessment => {
      assessment.weakAreas.forEach(area => weakConcepts.add(area))
    })

    if (weakConcepts.size === 0) {
      return this.createLowPriorityAction('log_event', { 
        message: 'No specific weak areas identified for additional help' 
      })
    }

    // Focus on the most common weak area
    const targetConcept = Array.from(weakConcepts)[0]
    
    // Generate additional help (examples, analogies, practice)
    const help = await this.createExplanation({
      concept: targetConcept,
      context,
      requestType: 'example'
    })

    return this.createAction('provide_explanation', {
      type: 'additional_help',
      targetConcept,
      weakAreas: Array.from(weakConcepts),
      additionalExamples: help.examples,
      practiceQuestions: help.followUpQuestions,
      analogies: help.analogies,
      reasoning: `Providing additional help for weak areas identified in recent assessments`
    }, 8)
  }

  private async adaptTeachingStyle(context: LearningContext): Promise<AgentAction> {
    const state = this.state as TutorAgentState
    
    // Analyze what hasn't been working
    const ineffectiveExplanations = state.explanationHistory.filter(e => 
      e.userFeedback === 'confusing' || e.userFeedback === 'too_hard'
    )

    // Determine adaptations needed
    const adaptations = this.analyzeNeededAdaptations(ineffectiveExplanations, context)
    
    // Update adaptation level
    state.adaptationLevel = (state.adaptationLevel || 0) + 1
    state.preferredExplanationStyle = adaptations.newStyle

    return this.createAction('log_event', {
      message: 'Adapting teaching style based on user feedback',
      data: {
        previousStyle: context.preferences.explanationStyle,
        newStyle: adaptations.newStyle,
        adaptationReason: adaptations.reason,
        adaptationLevel: state.adaptationLevel
      }
    }, 6)
  }

  private async updateConceptUnderstanding(context: LearningContext): Promise<AgentAction> {
    const state = this.state as TutorAgentState
    const recentAssessments = context.recentAssessments.slice(0, 3)
    
    // Update understanding levels based on assessment performance
    recentAssessments.forEach(assessment => {
      const moduleKey = `module_${assessment.moduleId}`
      
      // Update understanding based on score
      let understandingLevel = assessment.score
      
      // Adjust based on time taken (faster = better understanding)
      const expectedTime = 300 // 5 minutes baseline
      if (assessment.completionTime < expectedTime) {
        understandingLevel += 5 // Bonus for quick completion
      } else if (assessment.completionTime > expectedTime * 2) {
        understandingLevel -= 5 // Penalty for very slow completion
      }
      
      state.userUnderstanding[moduleKey] = Math.max(0, Math.min(100, understandingLevel))
      
      // Track specific concept understanding
      assessment.strengths.forEach(strength => {
        state.userUnderstanding[strength] = Math.min(100, (state.userUnderstanding[strength] || 70) + 10)
      })
      
      assessment.weakAreas.forEach(weakness => {
        state.userUnderstanding[weakness] = Math.max(0, (state.userUnderstanding[weakness] || 50) - 10)
      })
    })

    return this.createAction('log_event', {
      message: 'Updated concept understanding levels',
      data: {
        assessmentCount: recentAssessments.length,
        conceptsUpdated: Object.keys(state.userUnderstanding).length,
        averageUnderstanding: this.calculateAverageUnderstanding(state.userUnderstanding)
      }
    }, 4)
  }

  // =============================================================================
  // Content Generation (MVP Implementation)
  // =============================================================================

  private async createExplanation(request: ConceptExplanationRequest): Promise<Explanation> {
    // For MVP: Generate structured explanations based on concept and user profile
    // Future: This will be replaced with BAML calls
    
    const { concept, context, requestType, userQuestion } = request
    const userProfile = context.userProfile
    const state = this.state as TutorAgentState

    // Generate explanation based on user's preferred style
    const baseExplanation = this.generateBaseExplanation(concept, userProfile)
    const analogies = this.generatePhysicsAnalogies(concept, userProfile.preferences.explanationStyle)
    const examples = this.generateExamples(concept, userProfile.background)
    const followUpQuestions = this.generateFollowUpQuestions(concept, requestType)
    const relatedConcepts = this.getRelatedConcepts(concept)

    return {
      concept,
      explanation: baseExplanation,
      analogies,
      examples,
      followUpQuestions,
      relatedConcepts,
      difficultyLevel: this.determineDifficultyLevel(concept, context)
    }
  }

  private generateBaseExplanation(concept: string, userProfile: any): string {
    // MVP: Template-based explanations
    // Future: BAML-generated explanations
    
    const explanationTemplates = {
      'Introduction to Machine Learning': `Machine Learning is like teaching a computer to recognize patterns, similar to how you learned to recognize faces. Instead of programming explicit rules, we show the computer many examples and let it figure out the patterns. Think of it as training a very smart pattern-recognition system.`,
      
      'Linear Algebra for ML': `Linear Algebra in ML is like the mathematical language that computers use to process information. Vectors are like arrows pointing in space, and matrices are like organized tables of numbers. When we do ML, we're essentially doing lots of mathematical operations on these organized collections of numbers.`,
      
      'Statistics and Probability': `Statistics in ML is like being a detective with data. Probability tells us how likely something is to happen, and statistics helps us make sense of patterns in large amounts of information. It's the foundation for making predictions and understanding uncertainty.`,
      
      'Linear Regression': `Linear Regression is like drawing the best-fit line through a scatter plot of points. Imagine you're trying to predict house prices based on size - you'd draw a line that gets as close as possible to all the data points. That line becomes your prediction tool.`,
      
      'Neural Networks': `Neural Networks are inspired by how brain neurons work together. Just like your brain has billions of connected neurons processing information, artificial neural networks have mathematical "neurons" that work together to recognize patterns and make decisions.`
    }

    const baseExplanation = explanationTemplates[concept as keyof typeof explanationTemplates] || 
      `${concept} is an important concept in AI/ML that builds on fundamental mathematical and statistical principles. Let's break it down step by step.`

    // Adapt explanation based on user's learning style
    if (userProfile.learningStyle === 'visual') {
      return `${baseExplanation}\n\nTo visualize this: imagine ${this.getVisualizationPrompt(concept)}`
    } else if (userProfile.learningStyle === 'kinesthetic') {
      return `${baseExplanation}\n\nTo experience this hands-on: ${this.getHandsOnPrompt(concept)}`
    }

    return baseExplanation
  }

  private generatePhysicsAnalogies(concept: string, explanationStyle: string): string[] {
    if (explanationStyle !== 'physics_analogies') return []

    const physicsAnalogies = {
      'Introduction to Machine Learning': [
        'ML is like training a resonant circuit - you adjust parameters until the system naturally responds to the right frequencies',
        'Like how a prism separates white light into colors, ML algorithms separate complex data into recognizable patterns'
      ],
      'Linear Algebra for ML': [
        'Vectors are like force vectors in physics - they have magnitude and direction',
        'Matrix multiplication is like successive transformations of coordinates, similar to rotating reference frames'
      ],
      'Neural Networks': [
        'Neural networks are like electrical circuits with adjustable resistors - the weights change how signals flow through the network',
        'Backpropagation is like the principle of least action - the network finds the path that minimizes error'
      ],
      'Statistics and Probability': [
        'Probability distributions are like wave functions in quantum mechanics - they describe the likelihood of different outcomes',
        'Statistical sampling is like measuring particle positions - each measurement gives you information about the whole system'
      ]
    }

    return physicsAnalogies[concept as keyof typeof physicsAnalogies] || [
      `Think of ${concept} like a physical system where you're trying to find the equilibrium state`,
      `This concept works similarly to conservation laws in physics - certain properties remain constant`
    ]
  }

  private generateExamples(concept: string, background: string): string[] {
    const examples = {
      'Introduction to Machine Learning': [
        'Email spam detection: showing the computer thousands of spam vs non-spam emails',
        'Image recognition: training on millions of labeled photos',
        'Recommendation systems: learning from user behavior patterns'
      ],
      'Linear Regression': [
        'Predicting house prices based on square footage and location',
        'Estimating sales revenue from advertising spend',
        'Forecasting temperature based on historical data'
      ],
      'Neural Networks': [
        'Handwritten digit recognition (like reading ZIP codes)',
        'Language translation (Google Translate)',
        'Game playing (like AlphaGo or chess engines)'
      ]
    }

    const conceptExamples = examples[concept as keyof typeof examples] || [
      `Practical application of ${concept} in real-world scenarios`,
      `How ${concept} solves common problems in data science`
    ]

    // Adapt examples based on user background
    if (background.includes('software')) {
      return conceptExamples.map(ex => `Software example: ${ex}`)
    }

    return conceptExamples
  }

  private generateFollowUpQuestions(concept: string, requestType: string): string[] {
    const baseQuestions = [
      `What aspects of ${concept} would you like me to explain further?`,
      `Can you think of a real-world example where ${concept} might be useful?`,
      `What questions do you have about how ${concept} works in practice?`
    ]

    if (requestType === 'clarification') {
      return [
        'Does this explanation make more sense now?',
        'Would you like me to provide a different type of example?',
        'Is there a specific part that\'s still unclear?'
      ]
    }

    return baseQuestions
  }

  private getRelatedConcepts(concept: string): string[] {
    const conceptMap = {
      'Introduction to Machine Learning': ['Statistics and Probability', 'Linear Algebra for ML', 'Python for Data Science'],
      'Linear Regression': ['Statistics and Probability', 'Linear Algebra for ML', 'Gradient Descent'],
      'Neural Networks': ['Linear Algebra for ML', 'Calculus', 'Backpropagation'],
      'Statistics and Probability': ['Hypothesis Testing', 'Distributions', 'Bayesian Inference']
    }

    return conceptMap[concept as keyof typeof conceptMap] || []
  }

  private determineDifficultyLevel(concept: string, context: LearningContext): number {
    const module = context.availableModules.find(m => m.moduleName === concept)
    if (module) return module.difficultyLevel

    // Default difficulty estimation
    const difficultyMap = {
      'Introduction to Machine Learning': 2,
      'Statistics and Probability': 3,
      'Linear Algebra for ML': 4,
      'Linear Regression': 4,
      'Neural Networks': 6
    }

    return difficultyMap[concept as keyof typeof difficultyMap] || 5
  }

  private getVisualizationPrompt(concept: string): string {
    return `a graph or diagram showing how ${concept} transforms input data into useful outputs`
  }

  private getHandsOnPrompt(concept: string): string {
    return `try implementing a simple version of ${concept} with a small dataset to see how it works`
  }

  // =============================================================================
  // Analysis and Adaptation
  // =============================================================================

  private analyzeNeededAdaptations(ineffectiveExplanations: ExplanationRecord[], context: LearningContext): any {
    // Analyze what went wrong and suggest adaptations
    const currentStyle = context.preferences.explanationStyle
    
    // If physics analogies aren't working, try code examples
    if (currentStyle === 'physics_analogies') {
      return {
        newStyle: 'code_examples',
        reason: 'Physics analogies reported as confusing, switching to code examples'
      }
    }

    // If code examples aren't working, try step-by-step
    if (currentStyle === 'code_examples') {
      return {
        newStyle: 'step_by_step',
        reason: 'Code examples not effective, switching to step-by-step explanations'
      }
    }

    // Default adaptation
    return {
      newStyle: 'visual_diagrams',
      reason: 'Current explanation style not effective, trying visual approach'
    }
  }

  private calculateAverageUnderstanding(understanding: Record<string, number>): number {
    const values = Object.values(understanding)
    if (values.length === 0) return 0
    return values.reduce((sum, val) => sum + val, 0) / values.length
  }

  // =============================================================================
  // State Management
  // =============================================================================

  protected async initializeDefaultState(sessionId: number): Promise<void> {
    await super.initializeDefaultState(sessionId)
    
    const defaultState: TutorAgentState = {
      explanationHistory: [],
      userUnderstanding: {},
      preferredExplanationStyle: 'physics_analogies',
      sessionConcepts: [],
      adaptationLevel: 0
    }

    this.state = { ...this.state, ...defaultState }
  }

  private async updateInternalState(context: LearningContext): Promise<void> {
    const state = this.state as TutorAgentState
    
    // Update session concepts
    if (context.currentModule && !state.sessionConcepts.includes(context.currentModule.moduleName)) {
      state.sessionConcepts.push(context.currentModule.moduleName)
    }
    
    // Update last interaction time
    state.lastInteraction = new Date().toISOString()
  }

  // =============================================================================
  // Public Interface for Other Agents
  // =============================================================================

  async explainConcept(concept: string, context: LearningContext): Promise<Explanation> {
    // Public method for other agents to request explanations
    return await this.createExplanation({
      concept,
      context,
      requestType: 'initial'
    })
  }

  async getUserUnderstanding(concept: string): Promise<number> {
    const state = this.state as TutorAgentState
    return state.userUnderstanding[concept] || 0
  }

  async provideFeedback(concept: string, feedback: 'helpful' | 'confusing' | 'too_easy' | 'too_hard'): Promise<void> {
    const state = this.state as TutorAgentState
    const explanation = state.explanationHistory.find(e => e.concept === concept)
    if (explanation) {
      explanation.userFeedback = feedback
    }
  }
}