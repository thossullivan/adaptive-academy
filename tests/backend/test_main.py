"""Tests for backend FastAPI application."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock

# Add backend to path for testing
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.main import app


@pytest.fixture
def client():
    """Create test client for FastAPI app."""
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check and basic endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Adaptive Academy API is running" in response.json()["message"]
    
    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        assert response.json()["service"] == "adaptive-academy-backend"
    
    def test_agent_status_endpoint_no_api_key(self, client):
        """Test agent status endpoint without API key."""
        with patch('backend.main.os.getenv', return_value=None):
            response = client.get("/api/agents/status")
            assert response.status_code == 200
            data = response.json()
            assert data["api_key_configured"] is False
            assert data["status"] == "ready"
    
    def test_agent_status_endpoint_with_api_key(self, client):
        """Test agent status endpoint with API key."""
        with patch('backend.main.os.getenv', return_value='test-key'):
            response = client.get("/api/agents/status")
            assert response.status_code == 200
            data = response.json()
            assert data["api_key_configured"] is True
            assert data["status"] == "ready"


class TestTutorEndpoints:
    """Test tutor agent endpoints."""
    
    def test_teach_concept_no_api_key(self, client):
        """Test teach concept endpoint without API key."""
        with patch('backend.main.os.getenv', return_value=None):
            response = client.post("/api/tutor/teach", json={
                "concept": "linear regression",
                "user_context": {"background": "physics"}
            })
            assert response.status_code == 500
            assert "OpenAI API key not configured" in response.json()["detail"]
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.TutorAgent')
    def test_teach_concept_success(self, mock_tutor_class, mock_getenv, client):
        """Test successful concept teaching."""
        mock_getenv.return_value = 'test-key'
        
        mock_tutor = Mock()
        mock_tutor.teach_concept = AsyncMock(return_value="Linear regression is a statistical method...")
        mock_tutor_class.return_value = mock_tutor
        
        response = client.post("/api/tutor/teach", json={
            "concept": "linear regression",
            "user_context": {"background": "physics"}
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["concept"] == "linear regression"
        assert data["agent"] == "TutorAgent"
        assert "Linear regression is" in data["explanation"]
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.TutorAgent')
    def test_answer_question_success(self, mock_tutor_class, mock_getenv, client):
        """Test successful question answering."""
        mock_getenv.return_value = 'test-key'
        
        mock_tutor = Mock()
        mock_tutor.answer_student_question = AsyncMock(return_value="Great question! The answer is...")
        mock_tutor_class.return_value = mock_tutor
        
        response = client.post("/api/tutor/question", json={
            "question": "What is gradient descent?",
            "context": "learning about optimization",
            "user_level": "beginner"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["question"] == "What is gradient descent?"
        assert data["agent"] == "TutorAgent"
        assert "Great question" in data["answer"]
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.TutorAgent')
    def test_create_analogy_success(self, mock_tutor_class, mock_getenv, client):
        """Test successful analogy creation."""
        mock_getenv.return_value = 'test-key'
        
        mock_tutor = Mock()
        mock_tutor.create_physics_analogy = AsyncMock(return_value="Think of neural networks like electrical circuits...")
        mock_tutor_class.return_value = mock_tutor
        
        response = client.post("/api/tutor/analogy", json={
            "concept": "neural networks"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["concept"] == "neural networks"
        assert data["agent"] == "TutorAgent"
        assert "electrical circuits" in data["analogies"]


class TestCurriculumEndpoints:
    """Test curriculum director endpoints."""
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.CurriculumDirector')
    def test_create_curriculum_success(self, mock_director_class, mock_getenv, client):
        """Test successful curriculum creation."""
        mock_getenv.return_value = 'test-key'
        
        mock_director = Mock()
        mock_director.create_personalized_curriculum = AsyncMock(
            return_value="Complete ML curriculum with 6 modules..."
        )
        mock_director_class.return_value = mock_director
        
        response = client.post("/api/curriculum/create", json={
            "learning_goal": "Master machine learning",
            "student_profile": {
                "background": "software engineering",
                "time_per_week": "10 hours",
                "timeline": "6 months"
            }
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["learning_goal"] == "Master machine learning"
        assert data["agent"] == "CurriculumDirector"
        assert "curriculum with 6 modules" in data["curriculum"]
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.CurriculumDirector')
    def test_sequence_topics_success(self, mock_director_class, mock_getenv, client):
        """Test successful topic sequencing."""
        mock_getenv.return_value = 'test-key'
        
        mock_director = Mock()
        mock_director.sequence_learning_topics = AsyncMock(
            return_value="Optimal sequence: 1. Statistics, 2. Linear Algebra, 3. ML Basics..."
        )
        mock_director_class.return_value = mock_director
        
        response = client.post("/api/curriculum/sequence", json={
            "topics": ["Neural Networks", "Linear Algebra", "Statistics"],
            "student_level": "intermediate"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["topics"]) == 3
        assert data["agent"] == "CurriculumDirector"
        assert "Statistics" in data["sequence"]


class TestAssessmentEndpoints:
    """Test assessment coach endpoints."""
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.AssessmentCoach')
    def test_create_assessment_success(self, mock_coach_class, mock_getenv, client):
        """Test successful assessment creation."""
        mock_getenv.return_value = 'test-key'
        
        mock_coach = Mock()
        mock_coach.create_assessment = AsyncMock(
            return_value="5-question quiz on neural networks with multiple choice and short answer..."
        )
        mock_coach_class.return_value = mock_coach
        
        response = client.post("/api/assessment/create", json={
            "topic": "neural networks",
            "difficulty": 6,
            "question_count": 5,
            "objectives": ["understand backpropagation", "explain activation functions"]
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["topic"] == "neural networks"
        assert data["agent"] == "AssessmentCoach"
        assert "neural networks" in data["assessment"]
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.AssessmentCoach')
    def test_evaluate_performance_success(self, mock_coach_class, mock_getenv, client):
        """Test successful performance evaluation."""
        mock_getenv.return_value = 'test-key'
        
        mock_coach = Mock()
        mock_coach.evaluate_performance = AsyncMock(
            return_value="Student shows strong understanding of concepts but needs work on applications..."
        )
        mock_coach_class.return_value = mock_coach
        
        response = client.post("/api/assessment/evaluate", json={
            "topic": "linear regression",
            "student_responses": [
                {"question": "What is linear regression?", "answer": "A statistical method", "correct": True},
                {"question": "How do you calculate R-squared?", "answer": "Not sure", "correct": False}
            ]
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["topic"] == "linear regression"
        assert data["agent"] == "AssessmentCoach"
        assert "understanding of concepts" in data["evaluation"]


class TestErrorHandling:
    """Test error handling in API endpoints."""
    
    @patch('backend.main.os.getenv')
    @patch('backend.main.TutorAgent')
    def test_tutor_error_handling(self, mock_tutor_class, mock_getenv, client):
        """Test tutor error handling."""
        mock_getenv.return_value = 'test-key'
        
        mock_tutor = Mock()
        mock_tutor.teach_concept = AsyncMock(side_effect=Exception("Test error"))
        mock_tutor_class.return_value = mock_tutor
        
        response = client.post("/api/tutor/teach", json={
            "concept": "test topic"
        })
        
        assert response.status_code == 500
        assert "Error teaching concept" in response.json()["detail"]
    
    def test_invalid_request_data(self, client):
        """Test handling of invalid request data."""
        response = client.post("/api/tutor/teach", json={
            # Missing required 'concept' field
        })
        
        assert response.status_code == 422  # Unprocessable Entity