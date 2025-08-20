"""CurriculumDirector for planning personalized learning paths."""

import asyncio
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.messages import TextMessage, ChatMessage
from autogen_agentchat.base import Response


class CurriculumDirector:
    """AI agent specialized in creating personalized learning curricula.
    
    This agent provides:
    - Personalized learning path planning
    - Module sequencing based on prerequisites
    - Difficulty adaptation based on user progress
    - Learning goal setting and tracking
    """
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize the Curriculum Director agent.
        
        Args:
            model: OpenAI model to use (default: gpt-4)
            api_key: OpenAI API key (if not provided, will use environment variable)
        """
        self.model_client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
        
        system_message = """You are an expert curriculum designer and educational strategist specializing in AI/ML education. You have extensive experience in pedagogy, learning sciences, and adult education.

Core Responsibilities:
- Design personalized learning curricula based on individual needs and goals
- Sequence topics logically with proper prerequisite handling
- Adapt difficulty and pacing to learner progress
- Set realistic learning milestones and timelines
- Balance theory with practical application
- Ensure comprehensive coverage while maintaining engagement

Curriculum Design Principles:
1. **Prerequisite Mapping**: Ensure students have necessary background before advancing
2. **Scaffolding**: Build complexity gradually with proper support
3. **Just-in-Time Learning**: Introduce concepts when they're most relevant
4. **Multiple Learning Paths**: Accommodate different backgrounds and goals
5. **Practical Application**: Balance theory with hands-on projects
6. **Assessment Integration**: Plan checkpoints to measure progress
7. **Flexibility**: Allow for adaptive pacing based on mastery

Available Curriculum Tools:
- create_learning_path: Design complete curriculum for specific goals
- sequence_topics: Order topics with prerequisite consideration
- estimate_timeline: Calculate realistic timeframes for learning goals
- adapt_difficulty: Modify curriculum based on student performance
- recommend_projects: Suggest practical applications and exercises
- plan_assessments: Design evaluation checkpoints

Student Context Awareness:
- Prior experience and background knowledge
- Available time commitment and schedule constraints
- Learning goals (academic, professional, personal projects)
- Preferred learning modalities and pace
- Career objectives and application domains"""

        # Create curriculum planning tools
        self.tools = self._create_curriculum_tools()
        
        self.agent = AssistantAgent(
            name="CurriculumDirector",
            model_client=self.model_client,
            system_message=system_message,
            tools=self.tools,
        )
    
    def _create_curriculum_tools(self):
        """Create curriculum planning tools for the director agent."""
        
        def create_learning_path(goal: str, background: str, time_commitment: str, timeline: str = "3-6 months") -> str:
            """Create a comprehensive learning path for achieving a specific goal.
            
            Args:
                goal: Learning objective (e.g., "become ML engineer", "understand deep learning")
                background: Student's current knowledge and experience
                time_commitment: Available study time (e.g., "5 hours/week", "full-time")
                timeline: Desired completion timeframe
            
            Returns:
                Structured learning path with modules, timeline, and milestones
            """
            path_prompt = f"""
Create a comprehensive learning path to achieve: {goal}

Student Profile:
- Background: {background}
- Time Commitment: {time_commitment}
- Timeline: {timeline}

Design a curriculum with:
1. **Learning Path Overview**: High-level structure and approach
2. **Core Modules**: Sequential learning modules with:
   - Module name and objectives
   - Key concepts covered
   - Prerequisites
   - Estimated time investment
   - Practical exercises/projects
3. **Milestones**: Major checkpoints and achievements
4. **Assessment Strategy**: How progress will be measured
5. **Flexibility Points**: Where the path can adapt based on progress
6. **Resources**: Essential and supplementary materials
7. **Project Portfolio**: Culminating projects that demonstrate mastery

Ensure the path is realistic for the given time commitment and builds skills progressively.
"""
            return path_prompt
        
        def sequence_topics(topics: List[str], student_background: str = "beginner") -> str:
            """Sequence a list of topics in optimal learning order.
            
            Args:
                topics: List of topics to sequence
                student_background: Student's starting knowledge level
            
            Returns:
                Optimally sequenced topics with prerequisite explanations
            """
            topics_str = ", ".join(topics)
            sequence_prompt = f"""
Sequence these topics in optimal learning order for a {student_background}: {topics_str}

For each topic in the sequence, provide:
1. **Topic Name**
2. **Prerequisites**: What needs to be learned first
3. **Justification**: Why this position in the sequence
4. **Learning Objectives**: What student will achieve
5. **Connection to Next**: How it prepares for subsequent topics

Consider:
- Mathematical prerequisites
- Conceptual dependencies  
- Cognitive load progression
- Practical application readiness
"""
            return sequence_prompt
        
        def estimate_timeline(curriculum: str, time_per_week: int, student_pace: str = "average") -> str:
            """Estimate realistic timeline for curriculum completion.
            
            Args:
                curriculum: Description of the curriculum or learning goals
                time_per_week: Hours available per week for study
                student_pace: Learning pace (slow/average/fast)
            
            Returns:
                Detailed timeline with milestones and flexibility buffer
            """
            timeline_prompt = f"""
Estimate completion timeline for: {curriculum}

Parameters:
- Available time: {time_per_week} hours/week
- Learning pace: {student_pace}

Provide:
1. **Total Estimated Time**: Overall time investment needed
2. **Phase Breakdown**: Major learning phases with timeframes
3. **Weekly Schedule**: Sample weekly time allocation
4. **Milestone Timeline**: Key checkpoints with dates
5. **Buffer Time**: Extra time for review, catch-up, and deeper exploration
6. **Pace Variations**: How timeline changes with different learning speeds
7. **Optimization Tips**: How to make the most of available time

Consider realistic learning curves, retention needs, and practical application time.
"""
            return timeline_prompt
        
        def adapt_difficulty(current_performance: Dict[str, float], curriculum_section: str) -> str:
            """Adapt curriculum difficulty based on student performance.
            
            Args:
                current_performance: Performance metrics by topic/skill
                curriculum_section: Current section of curriculum being adapted
            
            Returns:
                Recommendations for difficulty adjustments and path modifications
            """
            performance_str = str(current_performance)
            adapt_prompt = f"""
Adapt curriculum difficulty for: {curriculum_section}

Current Performance Data: {performance_str}

Analyze performance and recommend:
1. **Performance Assessment**: Strengths and areas needing support
2. **Difficulty Adjustments**: Where to increase/decrease challenge
3. **Additional Support**: Extra resources for struggling areas
4. **Acceleration Opportunities**: Where student can advance faster
5. **Path Modifications**: Alternative approaches or topic reordering
6. **Remediation Plan**: Specific interventions for weak areas
7. **Motivation Strategies**: How to maintain engagement

Ensure recommendations maintain learning quality while adapting to student needs.
"""
            return adapt_prompt
        
        def recommend_projects(topics_covered: List[str], skill_level: str, career_goal: str = "general ML") -> str:
            """Recommend practical projects to reinforce learning.
            
            Args:
                topics_covered: List of topics student has learned
                skill_level: Current skill level (beginner/intermediate/advanced)
                career_goal: Target career or application area
            
            Returns:
                Portfolio of projects that demonstrate and build skills
            """
            topics_str = ", ".join(topics_covered)
            projects_prompt = f"""
Recommend practical projects for someone who has learned: {topics_str}

Student Profile:
- Skill Level: {skill_level}
- Career Goal: {career_goal}

Design a project portfolio with:
1. **Starter Project**: Immediate application of recent learning
2. **Skill Building Projects**: 2-3 projects that deepen understanding
3. **Integration Project**: Combines multiple concepts learned
4. **Portfolio Capstone**: Substantial project showcasing mastery
5. **Optional Extensions**: Advanced challenges for motivated learners

For each project, include:
- Learning objectives and skills demonstrated
- Estimated time and complexity
- Key deliverables and success metrics
- Real-world relevance and portfolio value
- Technical requirements and datasets
"""
            return projects_prompt
        
        def plan_assessments(learning_objectives: List[str], curriculum_length: str) -> str:
            """Plan assessment strategy for a curriculum.
            
            Args:
                learning_objectives: List of learning goals to assess
                curriculum_length: Duration of the curriculum (e.g., "3 months", "12 weeks")
            
            Returns:
                Comprehensive assessment plan with multiple evaluation methods
            """
            objectives_str = ", ".join(learning_objectives)
            assessment_prompt = f"""
Plan assessment strategy for curriculum with objectives: {objectives_str}

Curriculum Duration: {curriculum_length}

Design assessment plan with:
1. **Assessment Philosophy**: Approach to measuring learning
2. **Formative Assessments**: Ongoing progress checks
   - Frequency and format
   - Self-assessment opportunities
   - Peer review elements
3. **Summative Assessments**: Major evaluation points
   - Knowledge assessments
   - Practical skill evaluations
   - Project-based assessments
4. **Assessment Calendar**: When assessments occur throughout curriculum
5. **Feedback Mechanisms**: How students receive guidance
6. **Adaptive Elements**: How assessments inform curriculum adjustments
7. **Portfolio Development**: Building evidence of learning over time

Balance assessment load with learning time while ensuring comprehensive evaluation.
"""
            return assessment_prompt
        
        # Return list of tools
        return [
            create_learning_path,
            sequence_topics,
            estimate_timeline,
            adapt_difficulty,
            recommend_projects,
            plan_assessments
        ]
    
    async def create_personalized_curriculum(self, student_profile: Dict[str, Any], learning_goal: str) -> str:
        """Create a personalized curriculum for a student.
        
        Args:
            student_profile: Student background, goals, time commitment, etc.
            learning_goal: What the student wants to achieve
            
        Returns:
            Complete personalized curriculum plan
        """
        background = student_profile.get('background', 'beginner')
        time_commitment = student_profile.get('time_per_week', '5 hours/week')
        timeline = student_profile.get('timeline', '3-6 months')
        
        task = f"""Create a personalized curriculum for a student.

Learning Goal: {learning_goal}

Student Profile:
{student_profile}

Use your create_learning_path tool to design a comprehensive, personalized curriculum that matches their background, time availability, and goals."""

        try:
            response = await self.agent.run(task=task)
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error creating curriculum: {str(e)}"
    
    async def sequence_learning_topics(self, topics: List[str], student_level: str = "beginner") -> str:
        """Sequence topics in optimal learning order.
        
        Args:
            topics: List of topics to sequence
            student_level: Student's current level
            
        Returns:
            Optimally sequenced topics with explanations
        """
        task = f"""Sequence these learning topics in optimal order for a {student_level} student:

Topics: {', '.join(topics)}

Use your sequence_topics tool to create the best learning progression with clear prerequisite relationships."""

        try:
            response = await self.agent.run(task=task)
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error sequencing topics: {str(e)}"
    
    async def adapt_to_performance(self, performance_data: Dict[str, float], current_section: str) -> str:
        """Adapt curriculum based on student performance.
        
        Args:
            performance_data: Student performance metrics by topic
            current_section: Current curriculum section
            
        Returns:
            Adaptation recommendations for the curriculum
        """
        task = f"""Adapt the curriculum based on student performance data.

Current Section: {current_section}
Performance Data: {performance_data}

Use your adapt_difficulty tool to recommend curriculum adjustments that better match the student's demonstrated abilities and learning needs."""

        try:
            response = await self.agent.run(task=task)
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error adapting curriculum: {str(e)}"
    
    async def suggest_projects(self, completed_topics: List[str], skill_level: str, career_focus: str = "general") -> str:
        """Suggest practical projects for skill development.
        
        Args:
            completed_topics: Topics the student has completed
            skill_level: Current skill level
            career_focus: Career or application focus
            
        Returns:
            Recommended projects for skill development
        """
        task = f"""Recommend practical projects for skill development.

Completed Topics: {', '.join(completed_topics)}
Skill Level: {skill_level}  
Career Focus: {career_focus}

Use your recommend_projects tool to suggest a portfolio of projects that will reinforce learning and build practical skills."""

        try:
            response = await self.agent.run(task=task)
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error suggesting projects: {str(e)}"
    
    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()