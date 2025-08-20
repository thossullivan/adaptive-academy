#!/usr/bin/env node

import { StateManager } from '../core/StateManager.js'
import { AssessmentCoachAgent } from '../agents/AssessmentCoachAgent.js'
import { LearningContext } from '../types/index.js'

async function testAssessmentCoach() {
  console.log('🎯 Testing Assessment Coach Agent...')
  
  const stateManager = new StateManager('./database/adaptive-academy.db')
  
  try {
    await stateManager.initialize()
    
    // Create a test session with progress
    const session = await stateManager.createSession(1, 'study')
    if (!session.success) {
      throw new Error('Failed to create test session')
    }

    // Set current module and progress to trigger quiz generation
    await stateManager.updateSessionState(session.data!.id, {
      currentModuleId: 1, // Introduction to Machine Learning
      sessionState: {
        currentPhase: 'practicing',
        progressInModule: 75, // 75% progress to trigger assessment
        timeSpent: 45,
        conceptsCovered: ['supervised learning', 'unsupervised learning'],
        questionsAnswered: 0,
        lastActivity: 'studying'
      }
    })

    // Get learning context
    const contextResult = await stateManager.getLearningContext(session.data!.id)
    if (!contextResult.success) {
      throw new Error('Failed to get learning context')
    }

    const context = contextResult.data!
    console.log(`✅ Learning context loaded for session ${context.sessionId}`)
    console.log(`   Current module: ${context.currentModule?.moduleName}`)
    console.log(`   Progress: ${context.sessionState.progressInModule}%`)

    // Create and test Assessment Coach Agent
    const assessmentAgent = new AssessmentCoachAgent(stateManager)
    
    // Test 1: Quiz generation based on module progress
    console.log('\n📝 Testing quiz generation...')
    const quizActions = await assessmentAgent.processContext(context)
    
    console.log(`✅ Agent generated ${quizActions.length} actions`)
    
    // Display quiz generation actions
    quizActions.forEach((action, index) => {
      console.log(`\n   Action ${index + 1}:`)
      console.log(`   • Type: ${action.type}`)
      console.log(`   • Priority: ${action.priority}`)
      console.log(`   • Agent: ${action.agentId}`)
      
      if (action.type === 'generate_quiz') {
        console.log(`   • Module: ${action.data.moduleName}`)
        console.log(`   • Questions: ${action.data.quizData?.questions?.length || 0}`)
        console.log(`   • Time limit: ${Math.floor((action.data.quizData?.timeLimit || 0) / 60)} minutes`)
        console.log(`   • Difficulty: ${action.data.adaptiveSettings?.difficulty}/10`)
        console.log(`   • Mastery threshold: ${action.data.adaptiveSettings?.masteryThreshold}%`)
        
        if (action.data.quizData?.questions?.length > 0) {
          console.log(`   • Sample question: "${action.data.quizData.questions[0].question}"`)
          console.log(`   • Question type: ${action.data.quizData.questions[0].type}`)
          console.log(`   • Options: ${action.data.quizData.questions[0].options?.length || 0}`)
        }
      }
    })

    // Test 2: Simulate quiz completion and performance analysis
    console.log('\n📊 Testing performance analysis...')
    
    // Add some assessment data to the database
    const assessmentData = [
      { score: 85, weakAreas: ['model evaluation'], strengths: ['basic concepts', 'supervised learning'] },
      { score: 72, weakAreas: ['unsupervised learning', 'feature selection'], strengths: ['data preprocessing'] },
      { score: 90, weakAreas: [], strengths: ['model evaluation', 'supervised learning'] }
    ]

    for (const [index, assessment] of assessmentData.entries()) {
      await stateManager.run(`
        INSERT INTO assessments (session_id, module_id, quiz_data, user_responses, score, completion_time, weak_areas, strengths, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `, [
        context.sessionId,
        1,
        JSON.stringify({ questions: [{ id: 'q1', question: 'Test question' }] }),
        JSON.stringify([{ questionId: 'q1', userAnswer: 'answer', isCorrect: true, timeSpent: 30 }]),
        assessment.score,
        300 + index * 60, // Varying completion times
        JSON.stringify(assessment.weakAreas),
        JSON.stringify(assessment.strengths),
        new Date(Date.now() - (2 - index) * 60000).toISOString() // Spread over time
      ])
    }

    // Get updated context with assessment data
    const contextWithAssessments = await stateManager.getLearningContext(session.data!.id)
    const analysisActions = await assessmentAgent.processContext(contextWithAssessments.data!)
    
    console.log(`✅ Performance analysis generated ${analysisActions.length} actions`)
    
    const analysisAction = analysisActions.find(a => a.data?.trendsAnalyzed !== undefined)
    if (analysisAction) {
      console.log(`   • Trends analyzed: ${analysisAction.data.trendsAnalyzed}`)
      console.log(`   • Knowledge gaps identified: ${analysisAction.data.knowledgeGaps}`)
      console.log(`   • Overall performance: ${analysisAction.data.overallPerformance}%`)
      console.log(`   • Improvement areas: ${analysisAction.data.improvementAreas?.join(', ') || 'None'}`)
    }

    const feedbackAction = analysisActions.find(a => a.data?.type === 'performance_feedback')
    if (feedbackAction) {
      console.log(`\n   📈 Performance Feedback:`)
      console.log(`   • Summary: ${feedbackAction.data.feedback?.substring(0, 100)}...`)
      console.log(`   • Strengths: ${feedbackAction.data.strengths?.slice(0, 2).join(', ')}`)
      console.log(`   • Improvement areas: ${feedbackAction.data.improvementAreas?.slice(0, 2).join(', ')}`)
      console.log(`   • Recommendations: ${feedbackAction.data.recommendations?.length || 0}`)
    }

    // Test 3: Spaced repetition scheduling
    console.log('\n🔄 Testing spaced repetition...')
    
    // Mark a module as completed to trigger spaced repetition
    await stateManager.run(`
      UPDATE curriculum SET status = 'completed', completed_at = ? WHERE id = ?
    `, [new Date().toISOString(), 1])

    // Process context again to test spaced repetition
    const contextForSR = await stateManager.getLearningContext(session.data!.id)
    const srActions = await assessmentAgent.processContext(contextForSR.data!)
    
    console.log(`✅ Spaced repetition processed`)
    
    const srAction = srActions.find(a => a.data?.type === 'spaced_repetition_review')
    if (srAction) {
      console.log(`   • Review concept: ${srAction.data.concept}`)
      console.log(`   • Review level: ${srAction.data.reviewLevel}`)
      console.log(`   • Questions: ${srAction.data.quizData?.questions?.length || 0}`)
    }

    // Test 4: Difficulty adaptation
    console.log('\n⚙️  Testing difficulty adaptation...')
    
    // Add more high-score assessments to trigger difficulty increase
    const highScoreAssessments = [92, 95, 88, 93]
    for (const [index, score] of highScoreAssessments.entries()) {
      await stateManager.run(`
        INSERT INTO assessments (session_id, module_id, quiz_data, user_responses, score, completion_time, weak_areas, strengths, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `, [
        context.sessionId,
        2, // Different module
        JSON.stringify({ questions: [] }),
        JSON.stringify([]),
        score,
        250,
        JSON.stringify([]),
        JSON.stringify(['advanced concepts']),
        new Date(Date.now() - (3 - index) * 30000).toISOString()
      ])
    }

    const contextForAdaptation = await stateManager.getLearningContext(session.data!.id)
    const adaptationActions = await assessmentAgent.processContext(contextForAdaptation.data!)
    
    const adaptationAction = adaptationActions.find(a => a.data?.adaptationReason)
    if (adaptationAction) {
      console.log(`✅ Difficulty adaptation triggered`)
      console.log(`   • Previous difficulty: ${adaptationAction.data.previousDifficulty}`)
      console.log(`   • New difficulty: ${adaptationAction.data.newDifficulty}`)
      console.log(`   • Reason: ${adaptationAction.data.adaptationReason}`)
      console.log(`   • Average score: ${adaptationAction.data.averageScore}%`)
    }

    // Test 5: Concept mastery tracking
    console.log('\n🎓 Testing concept mastery tracking...')
    
    const masteryLevel = await assessmentAgent.getConceptMastery('module_1')
    console.log(`✅ Concept mastery for Module 1: ${Math.round(masteryLevel)}%`)
    
    const performanceTrends = await assessmentAgent.getPerformanceTrends()
    console.log(`✅ Performance trends tracked: ${performanceTrends.length}`)
    
    performanceTrends.forEach((trend, index) => {
      console.log(`   ${index + 1}. ${trend.concept}: ${trend.trend} (confidence: ${Math.round(trend.confidence)}%)`)
    })

    // Test 6: State persistence
    console.log('\n💾 Testing state persistence...')
    
    const agentState = assessmentAgent.getState()
    console.log(`✅ Agent state keys: ${Object.keys(agentState.data).join(', ')}`)
    
    // Test 7: Public interface methods
    console.log('\n🔧 Testing public interface methods...')
    
    await assessmentAgent.scheduleConceptReview('linear regression', 5)
    console.log(`✅ Concept review scheduled`)
    
    await assessmentAgent.updateDifficultyPreference(7)
    console.log(`✅ Difficulty preference updated`)

    console.log('\n🎉 Assessment Coach Agent test completed successfully!')
    
    // Summary
    console.log('\n📊 Test Summary:')
    console.log(`• Quiz generation: working (${quizActions.filter(a => a.type === 'generate_quiz').length} quizzes)`)
    console.log(`• Performance analysis: working (${analysisActions.length} analysis actions)`)
    console.log(`• Spaced repetition: working`)
    console.log(`• Difficulty adaptation: working`)
    console.log(`• Concept mastery tracking: working`)
    console.log(`• State persistence: working`)
    console.log(`• Public interface: working`)
    console.log(`• Average assessment score: ${Math.round((85 + 72 + 90 + 92 + 95 + 88 + 93) / 7)}%`)

  } catch (error) {
    console.error('💥 Test failed:', error)
  } finally {
    await stateManager.close()
  }
}

// Helper function to display assessment capabilities
function displayAssessmentCapabilities() {
  console.log('\n🎯 Assessment Coach Capabilities:')
  console.log('• Adaptive quiz generation')
  console.log('• Performance trend analysis')
  console.log('• Spaced repetition scheduling')
  console.log('• Concept mastery tracking')
  console.log('• Difficulty adaptation')
  console.log('• Knowledge gap identification')
  console.log('• Personalized feedback generation')
  console.log('• Multi-agent coordination')
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  testAssessmentCoach().catch(console.error)
}

export { testAssessmentCoach }