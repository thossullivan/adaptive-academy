"""SQLite database models and operations for Adaptive Academy."""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, asdict
from contextlib import contextmanager

# Import BAML types for type conversion
from baml_client.baml_client.types import (
    LearningProfile, Curriculum, CurriculumModule, 
    Quiz, Question, AssessmentResult
)

logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent / "adaptive-academy.db"


@dataclass
class UserProfile:
    """User profile data model."""
    id: Optional[int] = None
    background: str = ""
    hours_per_day: float = 2.0
    learning_style: str = "visual"
    current_focus: str = ""
    preferences: Dict[str, Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.preferences is None:
            self.preferences = {}


@dataclass
class LearningSession:
    """Learning session data model."""
    id: Optional[int] = None
    user_id: int = 1
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    current_module_id: Optional[int] = None
    session_state: Dict[str, Any] = None
    session_type: str = "study"
    
    def __post_init__(self):
        if self.session_state is None:
            self.session_state = {}
        if self.started_at is None:
            self.started_at = datetime.now()


@dataclass
class AgentState:
    """Agent state data model."""
    id: Optional[int] = None
    session_id: int = 0
    agent_type: str = ""
    state_data: Dict[str, Any] = None
    last_updated: Optional[datetime] = None
    
    def __post_init__(self):
        if self.state_data is None:
            self.state_data = {}
        if self.last_updated is None:
            self.last_updated = datetime.now()


class DatabaseManager:
    """Manages SQLite database operations."""
    
    def __init__(self, db_path: Union[str, Path] = DB_PATH):
        self.db_path = Path(db_path)
        self.ensure_database()
    
    def ensure_database(self):
        """Ensure database exists and is initialized."""
        if not self.db_path.exists():
            logger.info(f"Creating database at {self.db_path}")
            self.initialize_database()
        else:
            logger.debug(f"Database exists at {self.db_path}")
    
    def initialize_database(self):
        """Initialize database with schema."""
        schema_path = self.db_path.parent / "schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"Database schema not found at {schema_path}")
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            conn.commit()
            logger.info("Database initialized successfully")
    
    @contextmanager
    def get_connection(self):
        """Get database connection with proper error handling."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Enable dict-like access
            conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign keys
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def execute_query(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Execute a SELECT query and return results."""
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall()
    
    def execute_update(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT/UPDATE/DELETE query and return rows affected."""
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.rowcount
    
    def execute_insert(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT query and return the last insert ID."""
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.lastrowid
    
    # User Profile Operations
    
    def get_user_profile(self, user_id: int = 1) -> Optional[UserProfile]:
        """Get user profile by ID."""
        query = "SELECT * FROM user_profile WHERE id = ?"
        rows = self.execute_query(query, (user_id,))
        
        if not rows:
            return None
        
        row = rows[0]
        return UserProfile(
            id=row['id'],
            background=row['background'] or "",
            hours_per_day=row['hours_per_day'] or 2.0,
            learning_style=row['learning_style'] or "visual",
            current_focus=row['current_focus'] or "",
            preferences=json.loads(row['preferences']) if row['preferences'] else {},
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None
        )
    
    def update_user_profile(self, profile: UserProfile) -> bool:
        """Update user profile."""
        query = """
        UPDATE user_profile 
        SET background = ?, hours_per_day = ?, learning_style = ?, 
            current_focus = ?, preferences = ?
        WHERE id = ?
        """
        params = (
            profile.background,
            profile.hours_per_day,
            profile.learning_style,
            profile.current_focus,
            json.dumps(profile.preferences),
            profile.id
        )
        return self.execute_update(query, params) > 0
    
    def user_profile_to_baml(self, profile: UserProfile) -> LearningProfile:
        """Convert UserProfile to BAML LearningProfile."""
        return LearningProfile(
            background=profile.background,
            learning_style=profile.learning_style,
            time_commitment=f"{profile.hours_per_day} hours/day",
            goals=profile.preferences.get('goals', []),
            current_level=profile.preferences.get('current_level', 'intermediate')
        )
    
    # Learning Session Operations
    
    def create_session(self, session: LearningSession) -> int:
        """Create a new learning session."""
        query = """
        INSERT INTO learning_sessions (user_id, current_module_id, session_state, session_type)
        VALUES (?, ?, ?, ?)
        """
        params = (
            session.user_id,
            session.current_module_id,
            json.dumps(session.session_state),
            session.session_type
        )
        return self.execute_insert(query, params)
    
    def get_current_session(self, user_id: int = 1) -> Optional[LearningSession]:
        """Get the current active session for a user."""
        query = """
        SELECT * FROM learning_sessions 
        WHERE user_id = ? AND ended_at IS NULL 
        ORDER BY started_at DESC LIMIT 1
        """
        rows = self.execute_query(query, (user_id,))
        
        if not rows:
            return None
        
        row = rows[0]
        return LearningSession(
            id=row['id'],
            user_id=row['user_id'],
            started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
            ended_at=datetime.fromisoformat(row['ended_at']) if row['ended_at'] else None,
            current_module_id=row['current_module_id'],
            session_state=json.loads(row['session_state']) if row['session_state'] else {},
            session_type=row['session_type']
        )
    
    def end_session(self, session_id: int) -> bool:
        """End a learning session."""
        query = "UPDATE learning_sessions SET ended_at = CURRENT_TIMESTAMP WHERE id = ?"
        return self.execute_update(query, (session_id,)) > 0
    
    def update_session_state(self, session_id: int, state: Dict[str, Any]) -> bool:
        """Update session state."""
        query = "UPDATE learning_sessions SET session_state = ? WHERE id = ?"
        return self.execute_update(query, (json.dumps(state), session_id)) > 0
    
    # Agent State Operations
    
    def save_agent_state(self, agent_state: AgentState) -> bool:
        """Save or update agent state."""
        # Check if state exists
        existing_query = "SELECT id FROM agent_states WHERE session_id = ? AND agent_type = ?"
        existing = self.execute_query(existing_query, (agent_state.session_id, agent_state.agent_type))
        
        if existing:
            # Update existing state
            query = """
            UPDATE agent_states 
            SET state_data = ?, last_updated = CURRENT_TIMESTAMP 
            WHERE session_id = ? AND agent_type = ?
            """
            params = (json.dumps(agent_state.state_data), agent_state.session_id, agent_state.agent_type)
            return self.execute_update(query, params) > 0
        else:
            # Insert new state
            query = """
            INSERT INTO agent_states (session_id, agent_type, state_data)
            VALUES (?, ?, ?)
            """
            params = (agent_state.session_id, agent_state.agent_type, json.dumps(agent_state.state_data))
            return self.execute_insert(query, params) > 0
    
    def get_agent_state(self, session_id: int, agent_type: str) -> Optional[AgentState]:
        """Get agent state for a session."""
        query = "SELECT * FROM agent_states WHERE session_id = ? AND agent_type = ?"
        rows = self.execute_query(query, (session_id, agent_type))
        
        if not rows:
            return None
        
        row = rows[0]
        return AgentState(
            id=row['id'],
            session_id=row['session_id'],
            agent_type=row['agent_type'],
            state_data=json.loads(row['state_data']) if row['state_data'] else {},
            last_updated=datetime.fromisoformat(row['last_updated']) if row['last_updated'] else None
        )
    
    # Assessment Operations
    
    def save_assessment(self, session_id: int, module_id: int, quiz: Quiz, 
                       responses: Dict[str, str], result: AssessmentResult) -> int:
        """Save assessment results."""
        query = """
        INSERT INTO assessments (session_id, module_id, quiz_data, user_responses, 
                               score, completion_time, weak_areas, strengths)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            session_id,
            module_id,
            json.dumps(asdict(quiz)),
            json.dumps(responses),
            result.score_percentage,
            result.time_taken_minutes,
            json.dumps(result.weak_areas),
            json.dumps(result.strengths)
        )
        return self.execute_insert(query, params)
    
    def get_assessment_history(self, user_id: int, module_id: Optional[int] = None) -> List[AssessmentResult]:
        """Get assessment history for a user."""
        if module_id:
            query = """
            SELECT a.* FROM assessments a
            JOIN learning_sessions s ON a.session_id = s.id
            WHERE s.user_id = ? AND a.module_id = ?
            ORDER BY a.created_at DESC
            """
            params = (user_id, module_id)
        else:
            query = """
            SELECT a.* FROM assessments a
            JOIN learning_sessions s ON a.session_id = s.id
            WHERE s.user_id = ?
            ORDER BY a.created_at DESC
            """
            params = (user_id,)
        
        rows = self.execute_query(query, params)
        results = []
        
        for row in rows:
            result = AssessmentResult(
                quiz_id=f"assessment_{row['id']}",
                score_percentage=row['score'],
                time_taken_minutes=row['completion_time'],
                strengths=json.loads(row['strengths']) if row['strengths'] else [],
                weak_areas=json.loads(row['weak_areas']) if row['weak_areas'] else [],
                feedback="",  # Can be enhanced later
                recommendations=[]  # Can be enhanced later
            )
            results.append(result)
        
        return results
    
    # Curriculum Operations
    
    def get_available_modules(self, user_id: int = 1) -> List[Dict[str, Any]]:
        """Get available curriculum modules for a user."""
        query = """
        SELECT c.*, 
               CASE WHEN COUNT(a.id) > 0 THEN AVG(a.score) ELSE NULL END as avg_score,
               COUNT(a.id) as attempt_count
        FROM curriculum c
        LEFT JOIN assessments a ON c.id = a.module_id
        LEFT JOIN learning_sessions s ON a.session_id = s.id AND s.user_id = ?
        GROUP BY c.id
        ORDER BY c.difficulty_level, c.id
        """
        rows = self.execute_query(query, (user_id,))
        
        modules = []
        for row in rows:
            module = {
                'id': row['id'],
                'topic': row['topic'],
                'module_name': row['module_name'],
                'description': row['description'],
                'prerequisites': json.loads(row['prerequisites']) if row['prerequisites'] else [],
                'estimated_hours': row['estimated_hours'],
                'difficulty_level': row['difficulty_level'],
                'status': row['status'],
                'avg_score': row['avg_score'],
                'attempt_count': row['attempt_count']
            }
            modules.append(module)
        
        return modules
    
    def update_module_status(self, module_id: int, status: str) -> bool:
        """Update module status."""
        query = "UPDATE curriculum SET status = ? WHERE id = ?"
        return self.execute_update(query, (status, module_id)) > 0
    
    # Event Logging
    
    def log_event(self, session_id: int, agent_type: Optional[str], event_type: str, 
                  event_data: Dict[str, Any]) -> int:
        """Log a learning event."""
        query = """
        INSERT INTO learning_events (session_id, agent_type, event_type, event_data)
        VALUES (?, ?, ?, ?)
        """
        params = (session_id, agent_type, event_type, json.dumps(event_data))
        return self.execute_insert(query, params)


# Global database manager instance
db_manager = DatabaseManager()


def get_db() -> DatabaseManager:
    """Get the global database manager instance."""
    return db_manager