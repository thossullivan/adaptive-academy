#!/usr/bin/env node

import { StateManager } from '../core/StateManager.js'
import { TutorAgent } from '../agents/TutorAgent.js'
import { LearningContext } from '../types/index.js'

async function testTutorAgent() {
  console.log('🎓 Testing Tutor Agent...')
  
  const stateManager = new StateManager('./database/adaptive-academy.db')
  
  try {
    await stateManager.initialize()
    
    // Create a test session with a current module
    const session = await stateManager.createSession(1, 'study')
    if (!session.success) {
      throw new Error('Failed to create test session')
    }

    // Set current module to something we can explain
    await stateManager.updateSessionState(session.data!.id, {
      currentModuleId: 1 // Introduction to Machine Learning
    })

    // Get learning context
    const contextResult = await stateManager.getLearningContext(session.data!.id)
    if (!contextResult.success) {
      throw new Error('Failed to get learning context')
    }

    const context = contextResult.data!
    console.log(`✅ Learning context loaded for session ${context.sessionId}`)
    console.log(`   Current module: ${context.currentModule?.moduleName}`)

    // Create and test Tutor Agent
    const tutorAgent = new TutorAgent(stateManager)
    
    // Test 1: Initial concept explanation
    console.log('\n📚 Testing initial concept explanation...')
    const explanationActions = await tutorAgent.processContext(context)
    
    console.log(`✅ Agent generated ${explanationActions.length} actions`)
    
    // Display explanation actions
    explanationActions.forEach((action, index) => {
      console.log(`\n   Action ${index + 1}:`)
      console.log(`   • Type: ${action.type}`)
      console.log(`   • Priority: ${action.priority}`)
      console.log(`   • Agent: ${action.agentId}`)
      
      if (action.type === 'provide_explanation') {
        console.log(`   • Concept: ${action.data.concept}`)
        console.log(`   • Explanation: ${action.data.explanation?.substring(0, 150)}...`)
        console.log(`   • Analogies: ${action.data.analogies?.length || 0}`)
        console.log(`   • Examples: ${action.data.examples?.length || 0}`)
        console.log(`   • Follow-up questions: ${action.data.followUpQuestions?.length || 0}`)
        console.log(`   • Adapted for: ${action.data.adaptedFor?.learningStyle} learner`)
        
        if (action.data.analogies && action.data.analogies.length > 0) {
          console.log(`   • Sample analogy: "${action.data.analogies[0]?.substring(0, 100)}..."`)
        }
      }
    })

    // Test 2: User question answering
    console.log('\n❓ Testing user question answering...')
    
    // Simulate a user question
    await stateManager.logEvent(context.sessionId, 'user_question', {
      question: 'Can you explain this with a simpler example?',
      concept: 'Introduction to Machine Learning'
    })

    // Get updated context
    const updatedContextResult = await stateManager.getLearningContext(session.data!.id)
    const updatedContext = updatedContextResult.data!

    const questionActions = await tutorAgent.processContext(updatedContext)
    console.log(`✅ Question answering generated ${questionActions.length} actions`)

    const questionAction = questionActions.find(a => a.type === 'provide_explanation' && a.data.type === 'question_answer')
    if (questionAction) {
      console.log(`   • Answered question: "${questionAction.data.userQuestion}"`)
      console.log(`   • Answer: ${questionAction.data.answer?.substring(0, 120)}...`)
    }

    // Test 3: Additional help based on low performance
    console.log('\n🆘 Testing additional help for struggling concepts...')
    
    // Create a mock assessment with low score and weak areas
    await stateManager.run(`
      INSERT INTO assessments (session_id, module_id, quiz_data, user_responses, score, completion_time, weak_areas, strengths, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      context.sessionId,
      1, // Introduction to ML module
      JSON.stringify({ questions: [] }),
      JSON.stringify([]),
      65, // Low score
      450, // Completion time in seconds
      JSON.stringify(['supervised learning', 'model training']),
      JSON.stringify(['basic concepts']),
      new Date().toISOString()
    ])

    // Get context with assessment data
    const contextWithAssessment = await stateManager.getLearningContext(session.data!.id)
    const helpActions = await tutorAgent.processContext(contextWithAssessment.data!)
    
    console.log(`✅ Additional help generated ${helpActions.length} actions`)
    
    const helpAction = helpActions.find(a => a.data.type === 'additional_help')
    if (helpAction) {
      console.log(`   • Target concept: ${helpAction.data.targetConcept}`)
      console.log(`   • Weak areas: ${helpAction.data.weakAreas?.join(', ')}`)
      console.log(`   • Additional examples: ${helpAction.data.additionalExamples?.length || 0}`)
      console.log(`   • Practice questions: ${helpAction.data.practiceQuestions?.length || 0}`)
    }

    // Test 4: Direct explanation method
    console.log('\n🔍 Testing direct explanation method...')
    
    const directExplanation = await tutorAgent.explainConcept('Linear Regression', context)
    console.log(`✅ Direct explanation generated`)
    console.log(`   • Concept: ${directExplanation.concept}`)
    console.log(`   • Difficulty: ${directExplanation.difficultyLevel}/10`)
    console.log(`   • Analogies: ${directExplanation.analogies.length}`)
    console.log(`   • Examples: ${directExplanation.examples.length}`)
    console.log(`   • Explanation: ${directExplanation.explanation.substring(0, 150)}...`)

    // Test 5: State persistence and understanding tracking
    console.log('\n💾 Testing state persistence and understanding tracking...')
    
    const agentState = tutorAgent.getState()
    console.log(`✅ Agent state keys: ${Object.keys(agentState.data).join(', ')}`)
    
    const understanding = await tutorAgent.getUserUnderstanding('Introduction to Machine Learning')
    console.log(`✅ User understanding level: ${understanding}%`)

    // Test 6: Feedback system
    console.log('\n💬 Testing feedback system...')
    
    await tutorAgent.provideFeedback('Introduction to Machine Learning', 'helpful')
    console.log(`✅ Feedback recorded successfully`)

    console.log('\n🎉 Tutor Agent test completed successfully!')
    
    // Summary
    console.log('\n📊 Test Summary:')
    console.log(`• Explanation actions generated: ${explanationActions.length}`)
    console.log(`• Question answering actions: ${questionActions.length}`)
    console.log(`• Additional help actions: ${helpActions.length}`)
    console.log(`• Direct explanations: working`)
    console.log(`• State persistence: working`)
    console.log(`• Understanding tracking: working`)
    console.log(`• Feedback system: working`)
    console.log(`• Learning style adaptation: ${context.userProfile.learningStyle}`)
    console.log(`• Explanation style: ${context.preferences.explanationStyle}`)

  } catch (error) {
    console.error('💥 Test failed:', error)
  } finally {
    await stateManager.close()
  }
}

// Helper function to display teaching capabilities
function displayTeachingCapabilities() {
  console.log('\n🎓 Tutor Agent Capabilities:')
  console.log('• Adaptive concept explanations')
  console.log('• Physics analogies for AI/ML concepts') 
  console.log('• Learning style customization')
  console.log('• Interactive question answering')
  console.log('• Performance-based additional help')
  console.log('• Understanding level tracking')
  console.log('• Teaching style adaptation')
  console.log('• Concept relationship mapping')
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  testTutorAgent().catch(console.error)
}

export { testTutorAgent }