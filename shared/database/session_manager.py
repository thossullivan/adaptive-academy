"""Learning session management for Adaptive Academy."""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from .models import (
    DatabaseManager, UserProfile, LearningSession, AgentState,
    get_db
)
from baml_client.baml_client.types import LearningProfile

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages learning sessions and agent coordination."""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or get_db()
    
    def start_session(self, user_id: int = 1, module_id: Optional[int] = None,
                     session_type: str = "study") -> LearningSession:
        """Start a new learning session."""
        # End any existing active session
        current_session = self.get_current_session(user_id)
        if current_session:
            self.end_session(current_session.id)
            logger.info(f"Ended previous session {current_session.id}")
        
        # Create new session
        new_session = LearningSession(
            user_id=user_id,
            current_module_id=module_id,
            session_type=session_type,
            session_state={
                'started_at': datetime.now().isoformat(),
                'current_step': 'initialization',
                'agents_initialized': False
            }
        )
        
        session_id = self.db.create_session(new_session)
        new_session.id = session_id
        
        # Log session start event (use None for system events)
        self.db.log_event(
            session_id=session_id,
            agent_type=None,
            event_type="session_started",
            event_data={
                'user_id': user_id,
                'module_id': module_id,
                'session_type': session_type
            }
        )
        
        logger.info(f"Started new session {session_id} for user {user_id}")
        return new_session
    
    def get_current_session(self, user_id: int = 1) -> Optional[LearningSession]:
        """Get the current active session for a user."""
        return self.db.get_current_session(user_id)
    
    def end_session(self, session_id: int) -> bool:
        """End a learning session."""
        success = self.db.end_session(session_id)
        if success:
            # Log session end event (use None for system events)
            self.db.log_event(
                session_id=session_id,
                agent_type=None,
                event_type="session_ended",
                event_data={'ended_at': datetime.now().isoformat()}
            )
            logger.info(f"Ended session {session_id}")
        return success
    
    def update_session_progress(self, session_id: int, progress_data: Dict[str, Any]) -> bool:
        """Update session progress and state."""
        # Get current session state
        session = self.get_session_by_id(session_id)
        if not session:
            return False
        
        # Update state with new progress
        updated_state = session.session_state.copy()
        updated_state.update(progress_data)
        updated_state['last_updated'] = datetime.now().isoformat()
        
        return self.db.update_session_state(session_id, updated_state)
    
    def get_session_by_id(self, session_id: int) -> Optional[LearningSession]:
        """Get session by ID."""
        query = "SELECT * FROM learning_sessions WHERE id = ?"
        rows = self.db.execute_query(query, (session_id,))
        
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
    
    def get_user_learning_profile(self, user_id: int = 1) -> LearningProfile:
        """Get user's learning profile as BAML type."""
        profile = self.db.get_user_profile(user_id)
        if not profile:
            # Return default profile
            return LearningProfile(
                background="General background",
                learning_style="visual",
                time_commitment="2 hours/day",
                goals=["Learn AI/ML fundamentals"],
                current_level="beginner"
            )
        
        return self.db.user_profile_to_baml(profile)
    
    def save_agent_state(self, session_id: int, agent_type: str, state_data: Dict[str, Any]) -> bool:
        """Save agent state for a session."""
        agent_state = AgentState(
            session_id=session_id,
            agent_type=agent_type,
            state_data=state_data
        )
        
        success = self.db.save_agent_state(agent_state)
        if success:
            # Log agent state update
            self.db.log_event(
                session_id=session_id,
                agent_type=agent_type,
                event_type="agent_state_updated",
                event_data={'state_keys': list(state_data.keys())}
            )
        
        return success
    
    def get_agent_state(self, session_id: int, agent_type: str) -> Dict[str, Any]:
        """Get agent state for a session."""
        agent_state = self.db.get_agent_state(session_id, agent_type)
        return agent_state.state_data if agent_state else {}
    
    def initialize_agents(self, session_id: int) -> bool:
        """Initialize all agents for a session."""
        try:
            # Initialize each agent with empty state
            for agent_type in ['curriculum_director', 'tutor', 'assessment_coach']:
                initial_state = {
                    'initialized': True,
                    'initialized_at': datetime.now().isoformat(),
                    'context': {},
                    'last_action': None
                }
                self.save_agent_state(session_id, agent_type, initial_state)
            
            # Update session state
            self.update_session_progress(session_id, {
                'agents_initialized': True,
                'current_step': 'ready'
            })
            
            logger.info(f"Initialized all agents for session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize agents for session {session_id}: {e}")
            return False
    
    def get_session_context(self, session_id: int) -> Dict[str, Any]:
        """Get complete session context for agents."""
        session = self.get_session_by_id(session_id)
        if not session:
            return {}
        
        # Get user profile
        user_profile = self.get_user_learning_profile(session.user_id)
        
        # Get current module info if available
        current_module = None
        if session.current_module_id:
            modules = self.db.get_available_modules(session.user_id)
            current_module = next((m for m in modules if m['id'] == session.current_module_id), None)
        
        # Get agent states
        agent_states = {}
        for agent_type in ['curriculum_director', 'tutor', 'assessment_coach']:
            agent_states[agent_type] = self.get_agent_state(session_id, agent_type)
        
        # Get recent assessment history
        recent_assessments = self.db.get_assessment_history(session.user_id)[:5]  # Last 5
        
        return {
            'session': {
                'id': session.id,
                'user_id': session.user_id,
                'started_at': session.started_at.isoformat() if session.started_at else None,
                'session_type': session.session_type,
                'state': session.session_state
            },
            'user_profile': user_profile,
            'current_module': current_module,
            'agent_states': agent_states,
            'recent_assessments': [
                {
                    'quiz_id': r.quiz_id,
                    'score': r.score_percentage,
                    'strengths': r.strengths,
                    'weak_areas': r.weak_areas
                } for r in recent_assessments
            ],
            'available_modules': self.db.get_available_modules(session.user_id)
        }
    
    def log_agent_action(self, session_id: int, agent_type: str, action: str, 
                        action_data: Dict[str, Any]) -> None:
        """Log an agent action."""
        self.db.log_event(
            session_id=session_id,
            agent_type=agent_type,
            event_type=f"agent_action_{action}",
            event_data=action_data
        )
        
        # Update agent state with last action
        current_state = self.get_agent_state(session_id, agent_type)
        current_state['last_action'] = {
            'action': action,
            'timestamp': datetime.now().isoformat(),
            'data': action_data
        }
        self.save_agent_state(session_id, agent_type, current_state)
    
    def get_session_history(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get session history for a user."""
        query = """
        SELECT s.*, 
               COUNT(e.id) as event_count,
               COUNT(a.id) as assessment_count
        FROM learning_sessions s
        LEFT JOIN learning_events e ON s.id = e.session_id
        LEFT JOIN assessments a ON s.id = a.session_id
        WHERE s.user_id = ?
        GROUP BY s.id
        ORDER BY s.started_at DESC
        LIMIT ?
        """
        rows = self.db.execute_query(query, (user_id, limit))
        
        sessions = []
        for row in rows:
            session_data = {
                'id': row['id'],
                'started_at': row['started_at'],
                'ended_at': row['ended_at'],
                'session_type': row['session_type'],
                'current_module_id': row['current_module_id'],
                'event_count': row['event_count'],
                'assessment_count': row['assessment_count'],
                'duration_minutes': None
            }
            
            # Calculate duration if session ended
            if row['started_at'] and row['ended_at']:
                start = datetime.fromisoformat(row['started_at'])
                end = datetime.fromisoformat(row['ended_at'])
                session_data['duration_minutes'] = int((end - start).total_seconds() / 60)
            
            sessions.append(session_data)
        
        return sessions


# Global session manager instance
session_manager = SessionManager()


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    return session_manager