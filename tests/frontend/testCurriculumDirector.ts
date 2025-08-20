#!/usr/bin/env node

import { StateManager } from '../core/StateManager.js'
import { CurriculumDirectorAgent } from '../agents/CurriculumDirectorAgent.js'
import { LearningContext } from '../types/index.js'

async function testCurriculumDirector() {
  console.log('🧪 Testing Curriculum Director Agent...')
  
  const stateManager = new StateManager('./database/adaptive-academy.db')
  
  try {
    await stateManager.initialize()
    
    // Create a test session
    const session = await stateManager.createSession(1, 'study')
    if (!session.success) {
      throw new Error('Failed to create test session')
    }

    // Get learning context
    const contextResult = await stateManager.getLearningContext(session.data!.id)
    if (!contextResult.success) {
      throw new Error('Failed to get learning context')
    }

    const context = contextResult.data!
    console.log(`✅ Learning context loaded for session ${context.sessionId}`)

    // Create and test Curriculum Director Agent
    const curriculumAgent = new CurriculumDirectorAgent(stateManager)
    
    // Test initial curriculum generation
    console.log('\n📚 Testing initial curriculum generation...')
    const actions = await curriculumAgent.processContext(context)
    
    console.log(`✅ Agent generated ${actions.length} actions`)
    
    // Display actions
    actions.forEach((action, index) => {
      console.log(`\n   Action ${index + 1}:`)
      console.log(`   • Type: ${action.type}`)
      console.log(`   • Priority: ${action.priority}`)
      console.log(`   • Agent: ${action.agentId}`)
      
      if (action.type === 'update_curriculum') {
        console.log(`   • Recommended path: ${action.data.recommendedPath?.slice(0, 3).join(', ')}...`)
        console.log(`   • Estimated timeline: ${action.data.estimatedTimeline?.estimatedWeeks} weeks`)
      }
      
      if (action.type === 'recommend_module') {
        console.log(`   • Top recommendations: ${action.data.recommendations?.length || 0}`)
        action.data.recommendations?.slice(0, 2).forEach((rec: any, i: number) => {
          console.log(`     ${i + 1}. Module ${rec.moduleId} (Priority: ${rec.priority}, Confidence: ${rec.confidence}%)`)
          console.log(`        Reason: ${rec.reason}`)
        })
      }
    })

    // Test state persistence
    console.log('\n💾 Testing state persistence...')
    const agentState = curriculumAgent.getState()
    console.log(`✅ Agent state keys: ${Object.keys(agentState.data).join(', ')}`)

    // Simulate module completion and test adaptation
    console.log('\n🎯 Testing curriculum adaptation...')
    
    // Log a module completion event
    await stateManager.logEvent(context.sessionId, 'module_completed', {
      moduleId: context.availableModules[0]?.id,
      moduleName: context.availableModules[0]?.moduleName,
      score: 85
    })

    // Process context again to see adaptation
    const adaptationActions = await curriculumAgent.processContext(context)
    console.log(`✅ Adaptation generated ${adaptationActions.length} actions`)

    // Test error handling
    console.log('\n⚠️  Testing error handling...')
    try {
      // Create invalid context to test error handling
      const invalidContext = { ...context, sessionId: -1 } as LearningContext
      await curriculumAgent.processContext(invalidContext)
    } catch (error) {
      console.log(`✅ Error handling working: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }

    console.log('\n🎉 Curriculum Director Agent test completed successfully!')
    
    // Summary
    console.log('\n📊 Test Summary:')
    console.log(`• Initial actions generated: ${actions.length}`)
    console.log(`• Adaptation actions generated: ${adaptationActions.length}`)
    console.log(`• Available modules: ${context.availableModules.length}`)
    console.log(`• Learning goals: ${context.learningGoals.length}`)
    console.log(`• User learning style: ${context.userProfile.learningStyle}`)
    console.log(`• Daily hours: ${context.userProfile.hoursPerDay}`)

  } catch (error) {
    console.error('💥 Test failed:', error)
  } finally {
    await stateManager.close()
  }
}

// Helper function to display learning context details
function displayContextDetails(context: LearningContext) {
  console.log('\n📋 Learning Context Details:')
  console.log(`Session ID: ${context.sessionId}`)
  console.log(`User ID: ${context.userId}`)
  console.log(`Current Module: ${context.currentModule?.moduleName || 'None'}`)
  console.log(`Available Modules: ${context.availableModules.length}`)
  console.log(`Learning Goals: ${context.learningGoals.length}`)
  console.log(`Recent Assessments: ${context.recentAssessments.length}`)
  console.log(`Event History: ${context.eventHistory.length}`)
  
  console.log('\nTop 3 Available Modules:')
  context.availableModules.slice(0, 3).forEach((module, i) => {
    console.log(`${i + 1}. ${module.moduleName} (${module.estimatedHours}h, Level ${module.difficultyLevel}, Status: ${module.status})`)
  })
  
  console.log('\nLearning Goals:')
  context.learningGoals.forEach((goal, i) => {
    console.log(`${i + 1}. ${goal.title} (Priority: ${goal.priority}, Progress: ${goal.progressPercentage}%)`)
  })
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  testCurriculumDirector().catch(console.error)
}

export { testCurriculumDirector }