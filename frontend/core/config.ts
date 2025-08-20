// Configuration system for Adaptive Academy
// Designed for future extensibility including PostgreSQL migration

export interface DatabaseConfig {
  type: 'sqlite' | 'postgres'
  sqlite?: {
    path: string
    backupInterval?: number // hours
  }
  postgres?: {
    connectionString: string
    pool?: {
      min: number
      max: number
      idleTimeoutMillis: number
    }
  }
}

export interface LLMConfig {
  provider: 'claude' | 'openai' | 'local'
  apiKey?: string
  model: string
  temperature: number
  maxTokens: number
  timeout: number // seconds
}

export interface SystemConfig {
  database: DatabaseConfig
  llm: LLMConfig
  agents: {
    responseTimeout: number // seconds
    maxRetries: number
    logLevel: 'debug' | 'info' | 'warn' | 'error'
  }
  learning: {
    defaultSessionLength: number // minutes
    assessmentThreshold: number // score needed to pass (0-100)
    spacedRepetitionEnabled: boolean
    autoProgressTracking: boolean
  }
  features: {
    n8nIntegration: boolean
    obsidianIntegration: boolean
    analyticsEnabled: boolean
  }
}

// Default configuration for MVP
export const defaultConfig: SystemConfig = {
  database: {
    type: 'sqlite',
    sqlite: {
      path: './database/adaptive-academy.db',
      backupInterval: 24 // hours
    }
  },
  llm: {
    provider: 'claude',
    model: 'claude-3-haiku-20240307',
    temperature: 0.7,
    maxTokens: 2000,
    timeout: 30
  },
  agents: {
    responseTimeout: 30,
    maxRetries: 3,
    logLevel: 'info'
  },
  learning: {
    defaultSessionLength: 60, // 1 hour
    assessmentThreshold: 80,
    spacedRepetitionEnabled: true,
    autoProgressTracking: true
  },
  features: {
    n8nIntegration: false, // Enable in Phase 3
    obsidianIntegration: false, // Enable in Phase 3
    analyticsEnabled: true
  }
}

// Future: Factory function for database selection
// Will be implemented when PostgreSQL support is added
/*
export function createStateManager(config: DatabaseConfig): StateManager {
  switch (config.type) {
    case 'sqlite':
      return new SQLiteStateManager(config.sqlite!.path)
    case 'postgres':
      return new PostgreSQLStateManager(config.postgres!.connectionString)
    default:
      throw new Error(`Unsupported database type: ${config.type}`)
  }
}
*/

// Configuration loading and validation
export function loadConfig(): SystemConfig {
  // For MVP, use default config
  // Future: Load from environment variables or config file
  return defaultConfig
}

export function validateConfig(config: SystemConfig): string[] {
  const errors: string[] = []

  // Database validation
  if (config.database.type === 'sqlite' && !config.database.sqlite?.path) {
    errors.push('SQLite path is required when using SQLite')
  }
  if (config.database.type === 'postgres' && !config.database.postgres?.connectionString) {
    errors.push('Connection string is required when using PostgreSQL')
  }

  // LLM validation
  if (config.llm.provider !== 'local' && !config.llm.apiKey) {
    errors.push('API key is required for external LLM providers')
  }
  if (config.llm.temperature < 0 || config.llm.temperature > 2) {
    errors.push('LLM temperature must be between 0 and 2')
  }

  // Learning validation
  if (config.learning.assessmentThreshold < 0 || config.learning.assessmentThreshold > 100) {
    errors.push('Assessment threshold must be between 0 and 100')
  }

  return errors
}