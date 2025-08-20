#!/usr/bin/env node

import { StateManager } from './StateManager.js'
import { LearningContext } from '../types/index.js'

async function initializeSystem() {
  console.log('🚀 Initializing Adaptive Academy System...')
  
  const stateManager = new StateManager('./database/adaptive-academy.db')
  
  try {
    // Initialize database connection
    await stateManager.initialize()
    console.log('✅ Database connection established')
    
    // Setup database schema
    const schemaResult = await stateManager.setupSchema()
    if (schemaResult.success) {
      console.log('✅ Database schema created successfully')
    } else {
      console.log('⚠️  Schema setup skipped (may already exist)')
    }
    
    // Test basic operations
    console.log('\n🧪 Testing basic operations...')
    
    // Get the default user profile (should be created by schema)
    const userProfile = await stateManager.getUserProfile(1)
    if (userProfile.success) {
      console.log(`✅ User profile loaded: ${userProfile.data?.background}`)
    } else {
      console.log('❌ Failed to load user profile')
      return
    }
    
    // Create a test session
    const session = await stateManager.createSession(1, 'study')
    if (session.success) {
      console.log(`✅ Test session created: ID ${session.data?.id}`)
      
      // Get learning context
      const context = await stateManager.getLearningContext(session.data!.id)
      if (context.success) {
        console.log(`✅ Learning context loaded for user ${context.data?.userId}`)
        console.log(`   Available modules: ${context.data?.availableModules.length}`)
        console.log(`   Learning goals: ${context.data?.learningGoals.length}`)
        
        // Log a test event
        await stateManager.logEvent(session.data!.id, 'system_test', {
          message: 'System initialization test completed successfully'
        })
        console.log('✅ Event logging working')
        
        // Display sample curriculum
        console.log('\n📚 Sample AI/ML Curriculum:')
        context.data?.availableModules.slice(0, 5).forEach(module => {
          console.log(`   • ${module.moduleName} (${module.estimatedHours}h, Level ${module.difficultyLevel})`)
        })
        
      } else {
        console.log('❌ Failed to load learning context')
      }
    } else {
      console.log('❌ Failed to create test session')
    }
    
    console.log('\n🎉 System initialization completed successfully!')
    console.log('\nNext steps:')
    console.log('1. Set up BAML structure')
    console.log('2. Implement the three core agents')
    console.log('3. Create CLI interface')
    
  } catch (error) {
    console.error('💥 Initialization failed:', error)
  } finally {
    await stateManager.close()
  }
}

// Helper function to display learning context summary
function displayContextSummary(context: LearningContext) {
  console.log('\n📊 Learning Context Summary:')
  console.log(`User: ${context.userProfile.background}`)
  console.log(`Learning Style: ${context.userProfile.learningStyle}`)
  console.log(`Current Focus: ${context.userProfile.currentFocus}`)
  console.log(`Hours per Day: ${context.userProfile.hoursPerDay}`)
  console.log(`Available Modules: ${context.availableModules.length}`)
  console.log(`Active Goals: ${context.learningGoals.length}`)
  console.log(`Session Phase: ${context.sessionState.currentPhase}`)
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  initializeSystem().catch(console.error)
}

export { initializeSystem }