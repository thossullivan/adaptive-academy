-- Adaptive Academy Database Schema
-- SQLite database for learning session management and agent coordination

-- Enable foreign key constraints
PRAGMA foreign_keys = ON;

-- User profile and preferences
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY,
    background TEXT,
    hours_per_day REAL,
    learning_style TEXT CHECK (learning_style IN ('visual', 'auditory', 'kinesthetic', 'reading')),
    current_focus TEXT,
    preferences JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Learning curriculum modules
CREATE TABLE curriculum (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,
    module_name TEXT NOT NULL,
    description TEXT,
    prerequisites JSON, -- Array of module IDs: [1, 2, 3]
    estimated_hours REAL,
    difficulty_level INTEGER CHECK (difficulty_level BETWEEN 1 AND 10),
    status TEXT CHECK (status IN ('not_started', 'in_progress', 'completed')) DEFAULT 'not_started',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

-- Learning sessions - each study session
CREATE TABLE learning_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME,
    current_module_id INTEGER,
    session_state JSON, -- Current state of the session
    session_type TEXT CHECK (session_type IN ('study', 'review', 'assessment')),
    FOREIGN KEY (user_id) REFERENCES user_profile (id),
    FOREIGN KEY (current_module_id) REFERENCES curriculum (id)
);

-- Agent state tracking - persistent state for each agent
CREATE TABLE agent_states (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('curriculum_director', 'tutor', 'assessment_coach')),
    state_data JSON,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id),
    UNIQUE(session_id, agent_type)
);

-- Event logging for debugging and analytics
CREATE TABLE learning_events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    agent_type TEXT CHECK (agent_type IN ('curriculum_director', 'tutor', 'assessment_coach')),
    event_type TEXT NOT NULL,
    event_data JSON,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id)
);

-- Quiz and assessment data
CREATE TABLE assessments (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    module_id INTEGER NOT NULL,
    quiz_data JSON, -- Questions, options, correct answers
    user_responses JSON, -- User's answers
    score REAL CHECK (score BETWEEN 0 AND 100),
    completion_time INTEGER, -- seconds
    weak_areas JSON, -- Array of concepts that need work
    strengths JSON, -- Array of concepts mastered
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id),
    FOREIGN KEY (module_id) REFERENCES curriculum (id)
);

-- Performance metrics and analytics
CREATE TABLE performance_metrics (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    module_id INTEGER,
    metric_type TEXT NOT NULL, -- 'completion_time', 'quiz_score', 'concept_mastery', 'engagement'
    metric_value REAL,
    metadata JSON, -- Additional context for the metric
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES learning_sessions (id),
    FOREIGN KEY (module_id) REFERENCES curriculum (id)
);

-- Learning goals and objectives
CREATE TABLE learning_goals (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    goal_type TEXT CHECK (goal_type IN ('skill', 'knowledge', 'project', 'certification')),
    title TEXT NOT NULL,
    description TEXT,
    target_modules JSON, -- Array of module IDs that contribute to this goal
    target_date DATE,
    priority INTEGER CHECK (priority BETWEEN 1 AND 10),
    status TEXT CHECK (status IN ('active', 'completed', 'paused')) DEFAULT 'active',
    progress_percentage REAL DEFAULT 0 CHECK (progress_percentage BETWEEN 0 AND 100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_profile (id)
);

-- Indexes for performance optimization
CREATE INDEX idx_sessions_user ON learning_sessions(user_id);
CREATE INDEX idx_sessions_module ON learning_sessions(current_module_id);
CREATE INDEX idx_curriculum_status ON curriculum(status);
CREATE INDEX idx_curriculum_topic ON curriculum(topic);
CREATE INDEX idx_events_session ON learning_events(session_id);
CREATE INDEX idx_events_timestamp ON learning_events(timestamp);
CREATE INDEX idx_assessments_module ON assessments(module_id);
CREATE INDEX idx_assessments_session ON assessments(session_id);
CREATE INDEX idx_metrics_session_module ON performance_metrics(session_id, module_id);
CREATE INDEX idx_metrics_type ON performance_metrics(metric_type);
CREATE INDEX idx_agent_states_session ON agent_states(session_id);
CREATE INDEX idx_goals_user ON learning_goals(user_id);

-- Triggers for automatic timestamp updates
CREATE TRIGGER update_user_profile_timestamp 
    AFTER UPDATE ON user_profile
    BEGIN
        UPDATE user_profile SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

-- Trigger to automatically complete modules when assessment score is high
CREATE TRIGGER auto_complete_module
    AFTER INSERT ON assessments
    WHEN NEW.score >= 80
    BEGIN
        UPDATE curriculum 
        SET status = 'completed', completed_at = CURRENT_TIMESTAMP 
        WHERE id = NEW.module_id AND status = 'in_progress';
    END;

-- Trigger to log significant events
CREATE TRIGGER log_module_completion
    AFTER UPDATE OF status ON curriculum
    WHEN NEW.status = 'completed' AND OLD.status != 'completed'
    BEGIN
        INSERT INTO learning_events (session_id, event_type, event_data, timestamp)
        VALUES (
            (SELECT id FROM learning_sessions WHERE current_module_id = NEW.id ORDER BY started_at DESC LIMIT 1),
            'module_completed',
            json_object('module_id', NEW.id, 'module_name', NEW.module_name, 'topic', NEW.topic),
            CURRENT_TIMESTAMP
        );
    END;

-- Views for common queries

-- Current session view
CREATE VIEW current_sessions AS
SELECT 
    s.*,
    u.background,
    u.learning_style,
    c.module_name,
    c.topic,
    c.difficulty_level
FROM learning_sessions s
JOIN user_profile u ON s.user_id = u.id
LEFT JOIN curriculum c ON s.current_module_id = c.id
WHERE s.ended_at IS NULL;

-- Module progress view
CREATE VIEW module_progress AS
SELECT 
    c.*,
    COUNT(a.id) as assessment_count,
    AVG(a.score) as average_score,
    MAX(a.created_at) as last_assessment
FROM curriculum c
LEFT JOIN assessments a ON c.id = a.module_id
GROUP BY c.id;

-- User performance summary
CREATE VIEW user_performance AS
SELECT 
    u.id as user_id,
    COUNT(DISTINCT s.id) as total_sessions,
    COUNT(DISTINCT CASE WHEN c.status = 'completed' THEN c.id END) as completed_modules,
    COUNT(DISTINCT CASE WHEN c.status = 'in_progress' THEN c.id END) as active_modules,
    AVG(a.score) as average_quiz_score,
    SUM(c.estimated_hours) as total_study_hours
FROM user_profile u
LEFT JOIN learning_sessions s ON u.id = s.user_id
LEFT JOIN curriculum c ON s.current_module_id = c.id
LEFT JOIN assessments a ON s.id = a.session_id
GROUP BY u.id;

-- Initial data setup

-- Insert default user profile
INSERT INTO user_profile (background, hours_per_day, learning_style, current_focus, preferences)
VALUES (
    'Software engineering background with interest in AI/ML',
    2.0,
    'visual',
    'AI/ML fundamentals',
    json_object(
        'explanation_style', 'physics_analogies',
        'difficulty_preference', 'progressive',
        'assessment_frequency', 'weekly',
        'reminder_enabled', true
    )
);

-- Insert sample AI/ML curriculum
INSERT INTO curriculum (topic, module_name, description, prerequisites, estimated_hours, difficulty_level) VALUES
('AI/ML Fundamentals', 'Introduction to Machine Learning', 'Overview of ML concepts, types of learning, and basic terminology', json_array(), 8.0, 2),
('AI/ML Fundamentals', 'Linear Algebra for ML', 'Vectors, matrices, and operations essential for ML', json_array(), 12.0, 4),
('AI/ML Fundamentals', 'Statistics and Probability', 'Statistical foundations for machine learning', json_array(), 10.0, 3),
('AI/ML Fundamentals', 'Python for Data Science', 'NumPy, Pandas, and Matplotlib fundamentals', json_array(), 15.0, 3),
('Supervised Learning', 'Linear Regression', 'Understanding and implementing linear regression', json_array(1, 2, 3, 4), 8.0, 4),
('Supervised Learning', 'Logistic Regression', 'Classification using logistic regression', json_array(1, 2, 3, 5), 6.0, 4),
('Supervised Learning', 'Decision Trees', 'Tree-based learning algorithms', json_array(1, 3, 4), 8.0, 5),
('Supervised Learning', 'Random Forests', 'Ensemble methods and random forests', json_array(7), 6.0, 5),
('Neural Networks', 'Perceptron and Basic Neural Networks', 'Introduction to neural networks', json_array(1, 2, 3, 5), 10.0, 6),
('Neural Networks', 'Deep Learning Fundamentals', 'Multi-layer networks and backpropagation', json_array(9), 12.0, 7);

-- Insert sample learning goals
INSERT INTO learning_goals (user_id, goal_type, title, description, target_modules, target_date, priority) VALUES
(1, 'skill', 'Master ML Fundamentals', 'Complete foundational ML concepts', json_array(1, 2, 3, 4), '2024-12-31', 9),
(1, 'knowledge', 'Understand Supervised Learning', 'Gain proficiency in supervised learning algorithms', json_array(5, 6, 7, 8), '2025-02-28', 8),
(1, 'project', 'Build First ML Model', 'Create and deploy a complete ML model', json_array(5, 6, 7), '2025-01-31', 7);