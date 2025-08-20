"""FastAPI application for Adaptive Academy backend."""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import os
import json
import asyncio
from dotenv import load_dotenv

from .agents import TutorAgent, CurriculumDirector, AssessmentCoach

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Adaptive Academy API",
    description="AI-powered personalized learning platform with AI tutoring agents",
    version="0.1.0"
)

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize AI agents (will be created on first use)
tutor_agent = None
curriculum_director = None
assessment_coach = None

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_sessions: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.user_sessions[user_id] = websocket

    def disconnect(self, websocket: WebSocket, user_id: str):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]

    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.user_sessions:
            await self.user_sessions[user_id].send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()


def get_tutor_agent() -> TutorAgent:
    """Get or create the tutor agent."""
    global tutor_agent
    if tutor_agent is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="OpenAI API key not configured")
        tutor_agent = TutorAgent(api_key=api_key)
    return tutor_agent


def get_curriculum_director() -> CurriculumDirector:
    """Get or create the curriculum director."""
    global curriculum_director
    if curriculum_director is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="OpenAI API key not configured")
        curriculum_director = CurriculumDirector(api_key=api_key)
    return curriculum_director


def get_assessment_coach() -> AssessmentCoach:
    """Get or create the assessment coach."""
    global assessment_coach
    if assessment_coach is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="OpenAI API key not configured")
        assessment_coach = AssessmentCoach(api_key=api_key)
    return assessment_coach


# Pydantic models for API requests
class TeachConceptRequest(BaseModel):
    concept: str
    user_context: Optional[Dict[str, Any]] = None


class QuestionRequest(BaseModel):
    question: str
    context: str = ""
    user_level: str = "intermediate"


class CreateCurriculumRequest(BaseModel):
    learning_goal: str
    student_profile: Dict[str, Any]


class SequenceTopicsRequest(BaseModel):
    topics: List[str]
    student_level: str = "beginner"


class CreateAssessmentRequest(BaseModel):
    topic: str
    difficulty: int = 5
    question_count: int = 5
    objectives: Optional[List[str]] = None


class EvaluatePerformanceRequest(BaseModel):
    student_responses: List[Dict[str, Any]]
    topic: str


# Health check endpoints
@app.get("/")
async def root():
    """Root endpoint for health check."""
    return {"message": "Adaptive Academy API is running!"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "adaptive-academy-backend"}


# Tutor Agent Endpoints
@app.post("/api/tutor/teach")
async def teach_concept(request: TeachConceptRequest):
    """Have the tutor explain a concept to the student."""
    try:
        tutor = get_tutor_agent()
        explanation = await tutor.teach_concept(request.concept, request.user_context)
        return {
            "concept": request.concept,
            "explanation": explanation,
            "agent": "TutorAgent"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error teaching concept: {str(e)}")


@app.post("/api/tutor/question")
async def answer_question(request: QuestionRequest):
    """Have the tutor answer a student's question."""
    try:
        tutor = get_tutor_agent()
        answer = await tutor.answer_student_question(
            request.question, 
            request.context, 
            request.user_level
        )
        return {
            "question": request.question,
            "answer": answer,
            "agent": "TutorAgent"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error answering question: {str(e)}")


@app.post("/api/tutor/analogy")
async def create_physics_analogy(request: TeachConceptRequest):
    """Create physics analogies for ML concepts."""
    try:
        tutor = get_tutor_agent()
        analogies = await tutor.create_physics_analogy(request.concept)
        return {
            "concept": request.concept,
            "analogies": analogies,
            "agent": "TutorAgent"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating analogy: {str(e)}")


# Curriculum Director Endpoints
@app.post("/api/curriculum/create")
async def create_curriculum(request: CreateCurriculumRequest):
    """Create a personalized curriculum for the student."""
    try:
        director = get_curriculum_director()
        curriculum = await director.create_personalized_curriculum(
            request.student_profile,
            request.learning_goal
        )
        return {
            "learning_goal": request.learning_goal,
            "curriculum": curriculum,
            "agent": "CurriculumDirector"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating curriculum: {str(e)}")


@app.post("/api/curriculum/sequence")
async def sequence_topics(request: SequenceTopicsRequest):
    """Sequence learning topics in optimal order."""
    try:
        director = get_curriculum_director()
        sequence = await director.sequence_learning_topics(
            request.topics,
            request.student_level
        )
        return {
            "topics": request.topics,
            "sequence": sequence,
            "agent": "CurriculumDirector"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sequencing topics: {str(e)}")


# Assessment Coach Endpoints
@app.post("/api/assessment/create")
async def create_assessment(request: CreateAssessmentRequest):
    """Create an assessment for a topic."""
    try:
        coach = get_assessment_coach()
        assessment = await coach.create_assessment(
            request.topic,
            request.difficulty,
            request.question_count,
            request.objectives
        )
        return {
            "topic": request.topic,
            "assessment": assessment,
            "agent": "AssessmentCoach"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating assessment: {str(e)}")


@app.post("/api/assessment/evaluate")
async def evaluate_performance(request: EvaluatePerformanceRequest):
    """Evaluate student performance on an assessment."""
    try:
        coach = get_assessment_coach()
        evaluation = await coach.evaluate_performance(
            request.student_responses,
            request.topic
        )
        return {
            "topic": request.topic,
            "evaluation": evaluation,
            "agent": "AssessmentCoach"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating performance: {str(e)}")


# Agent status endpoint
@app.get("/api/agents/status")
async def get_agents_status():
    """Get the status of all AI agents."""
    return {
        "agents": {
            "tutor": tutor_agent is not None,
            "curriculum_director": curriculum_director is not None,
            "assessment_coach": assessment_coach is not None
        },
        "api_key_configured": os.getenv("OPENAI_API_KEY") is not None,
        "status": "ready"
    }


# WebSocket endpoints for real-time agent communication
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for real-time agent communication."""
    await manager.connect(websocket, user_id)
    
    try:
        # Send welcome message
        await manager.send_personal_message(
            json.dumps({
                "type": "connection",
                "message": f"Connected to Adaptive Academy learning session",
                "user_id": user_id,
                "timestamp": asyncio.get_event_loop().time()
            }),
            user_id
        )
        
        while True:
            # Wait for message from client
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_websocket_message(message, user_id)
            except json.JSONDecodeError:
                await manager.send_personal_message(
                    json.dumps({
                        "type": "error",
                        "message": "Invalid JSON format"
                    }),
                    user_id
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)


async def handle_websocket_message(message: Dict[str, Any], user_id: str):
    """Handle incoming WebSocket messages from the client."""
    message_type = message.get("type")
    
    try:
        if message_type == "tutor_question":
            # Handle real-time tutoring questions
            question = message.get("question", "")
            context = message.get("context", "")
            user_level = message.get("user_level", "intermediate")
            
            if not os.getenv("OPENAI_API_KEY"):
                await manager.send_personal_message(
                    json.dumps({
                        "type": "error",
                        "message": "AI agents not configured - missing API key"
                    }),
                    user_id
                )
                return
            
            # Send "thinking" message
            await manager.send_personal_message(
                json.dumps({
                    "type": "agent_thinking",
                    "agent": "TutorAgent",
                    "message": "Let me think about that question..."
                }),
                user_id
            )
            
            # Get tutor response
            tutor = get_tutor_agent()
            answer = await tutor.answer_student_question(question, context, user_level)
            
            # Send response
            await manager.send_personal_message(
                json.dumps({
                    "type": "tutor_response",
                    "agent": "TutorAgent",
                    "question": question,
                    "answer": answer,
                    "timestamp": asyncio.get_event_loop().time()
                }),
                user_id
            )
            
        elif message_type == "concept_explanation":
            # Handle concept explanation requests
            concept = message.get("concept", "")
            user_context = message.get("user_context", {})
            
            if not os.getenv("OPENAI_API_KEY"):
                await manager.send_personal_message(
                    json.dumps({
                        "type": "error", 
                        "message": "AI agents not configured - missing API key"
                    }),
                    user_id
                )
                return
            
            # Send "thinking" message
            await manager.send_personal_message(
                json.dumps({
                    "type": "agent_thinking",
                    "agent": "TutorAgent",
                    "message": f"Let me explain {concept} for you..."
                }),
                user_id
            )
            
            # Get explanation
            tutor = get_tutor_agent()
            explanation = await tutor.teach_concept(concept, user_context)
            
            # Send response
            await manager.send_personal_message(
                json.dumps({
                    "type": "concept_explanation",
                    "agent": "TutorAgent",
                    "concept": concept,
                    "explanation": explanation,
                    "timestamp": asyncio.get_event_loop().time()
                }),
                user_id
            )
            
        elif message_type == "curriculum_request":
            # Handle curriculum planning requests
            learning_goal = message.get("learning_goal", "")
            student_profile = message.get("student_profile", {})
            
            if not os.getenv("OPENAI_API_KEY"):
                await manager.send_personal_message(
                    json.dumps({
                        "type": "error",
                        "message": "AI agents not configured - missing API key"
                    }),
                    user_id
                )
                return
            
            # Send "thinking" message
            await manager.send_personal_message(
                json.dumps({
                    "type": "agent_thinking",
                    "agent": "CurriculumDirector",
                    "message": "Creating your personalized learning path..."
                }),
                user_id
            )
            
            # Get curriculum
            director = get_curriculum_director()
            curriculum = await director.create_personalized_curriculum(student_profile, learning_goal)
            
            # Send response
            await manager.send_personal_message(
                json.dumps({
                    "type": "curriculum_response",
                    "agent": "CurriculumDirector",
                    "learning_goal": learning_goal,
                    "curriculum": curriculum,
                    "timestamp": asyncio.get_event_loop().time()
                }),
                user_id
            )
            
        else:
            # Unknown message type
            await manager.send_personal_message(
                json.dumps({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                }),
                user_id
            )
            
    except Exception as e:
        # Handle errors gracefully
        await manager.send_personal_message(
            json.dumps({
                "type": "error",
                "message": f"Error processing request: {str(e)}"
            }),
            user_id
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)