"""AssessmentCoach for creating and evaluating learning assessments."""

import asyncio
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.messages import TextMessage, ChatMessage
from autogen_agentchat.base import Response


class AssessmentCoach:
    """AI agent specialized in creating and evaluating learning assessments.
    
    This agent provides:
    - Quiz and assessment creation tailored to learning objectives
    - Performance evaluation and feedback
    - Learning gap identification
    - Progress tracking and analytics
    """
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize the Assessment Coach agent.
        
        Args:
            model: OpenAI model to use (default: gpt-4)
            api_key: OpenAI API key (if not provided, will use environment variable)
        """
        self.model_client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
        
        system_message = """You are an expert educational assessment specialist with deep expertise in learning evaluation, psychometrics, and AI/ML education. You understand how to measure learning effectively and provide actionable feedback.

Core Responsibilities:
- Create diverse, effective assessments that measure true understanding
- Design questions that reveal conceptual understanding vs. memorization
- Provide detailed, constructive feedback on student performance
- Identify learning gaps and recommend targeted interventions
- Track learning progress over time with meaningful analytics
- Adapt assessment difficulty to challenge students appropriately

Assessment Design Principles:
1. **Alignment**: Assessments directly measure stated learning objectives
2. **Bloom's Taxonomy**: Questions span knowledge, comprehension, application, analysis
3. **Authenticity**: Real-world relevance and practical application
4. **Fairness**: Accessible to diverse learners and backgrounds
5. **Formative Focus**: Emphasis on learning improvement over grading
6. **Multiple Formats**: Varied question types to accommodate different strengths
7. **Progressive Difficulty**: Scaffold from basic to advanced understanding

Available Assessment Tools:
- create_quiz: Generate quizzes for specific topics and objectives
- design_project_assessment: Create project-based evaluation rubrics
- analyze_performance: Evaluate student responses and identify patterns
- provide_feedback: Give constructive, specific feedback on answers
- identify_gaps: Find knowledge gaps and misconceptions
- track_progress: Monitor learning trajectory over time
- recommend_practice: Suggest targeted practice for improvement

Question Types Expertise:
- Multiple choice with well-designed distractors
- Short answer that tests conceptual understanding
- Code implementation and debugging exercises
- Case study analysis and problem-solving
- Concept mapping and relationship identification
- Practical application scenarios"""

        # Create assessment tools
        self.tools = self._create_assessment_tools()
        
        self.agent = AssistantAgent(
            name="AssessmentCoach",
            model_client=self.model_client,
            system_message=system_message,
            tools=self.tools,
        )
    
    def _create_assessment_tools(self):
        """Create assessment tools for the coach agent."""
        
        def create_quiz(topic: str, difficulty_level: int = 5, question_count: int = 5, objectives: List[str] = None) -> str:
            """Create a quiz for a specific topic.
            
            Args:
                topic: The topic to assess (e.g., "linear regression", "neural networks")
                difficulty_level: Complexity level 1-10 (1=basic recall, 10=expert synthesis)
                question_count: Number of questions to generate
                objectives: Specific learning objectives to assess
            
            Returns:
                Complete quiz with questions, answers, and explanations
            """
            objectives_str = ", ".join(objectives) if objectives else "general understanding"
            quiz_prompt = f"""
Create a {question_count}-question quiz on {topic} at difficulty level {difficulty_level}/10.

Learning Objectives to Assess: {objectives_str}

Generate a comprehensive quiz with:

1. **Quiz Overview**:
   - Topic and objectives covered
   - Estimated time to complete
   - Difficulty level explanation

2. **Questions** (varied types):
   - Multiple choice with 4 options each
   - Short answer conceptual questions
   - Practical application problems
   - Code/math problems if relevant

3. **Answer Key**:
   - Correct answers for all questions
   - Detailed explanations for each answer
   - Common wrong answers and why they're incorrect

4. **Assessment Rubric**:
   - Scoring criteria for each question type
   - Performance indicators (excellent/good/needs work)
   - Learning gap indicators

Ensure questions test understanding, not just memorization, and include real-world applications where appropriate.
"""
            return quiz_prompt
        
        def design_project_assessment(project_description: str, learning_goals: List[str], skill_level: str = "intermediate") -> str:
            """Design assessment criteria for project-based learning.
            
            Args:
                project_description: Description of the project to assess
                learning_goals: What the project should demonstrate
                skill_level: Expected skill level of students
            
            Returns:
                Project assessment rubric with criteria and scoring
            """
            goals_str = ", ".join(learning_goals)
            project_prompt = f"""
Design assessment criteria for this project: {project_description}

Learning Goals: {goals_str}
Student Level: {skill_level}

Create a comprehensive project assessment with:

1. **Assessment Overview**:
   - Project summary and key learning demonstrations
   - Assessment philosophy and approach
   - Timeline and milestone checkpoints

2. **Evaluation Rubric**:
   - Technical competency criteria
   - Conceptual understanding indicators
   - Implementation quality measures
   - Communication and presentation skills

3. **Scoring Guidelines**:
   - Excellent (A): What exceptional work looks like
   - Proficient (B): Meeting expectations fully
   - Developing (C): Partial mastery, areas for growth
   - Beginning (D): Significant gaps, needs support

4. **Feedback Framework**:
   - Strengths identification process
   - Growth area specification
   - Specific improvement recommendations
   - Next learning steps

5. **Self-Assessment Component**:
   - Reflection questions for students
   - Self-evaluation criteria
   - Goal setting for future learning

Make criteria specific, observable, and actionable for both student and instructor use.
"""
            return project_prompt
        
        def analyze_performance(student_responses: List[Dict[str, Any]], quiz_topic: str) -> str:
            """Analyze student performance on assessments.
            
            Args:
                student_responses: List of student responses with questions and answers
                quiz_topic: Topic that was assessed
            
            Returns:
                Detailed performance analysis with insights and recommendations
            """
            responses_str = str(student_responses)
            analysis_prompt = f"""
Analyze student performance on {quiz_topic} assessment.

Student Responses: {responses_str}

Provide comprehensive performance analysis:

1. **Overall Performance Summary**:
   - Correct answer percentage
   - Question type performance breakdown
   - Time taken vs. expected
   - Difficulty level appropriateness

2. **Strengths Identified**:
   - Concepts well understood
   - Strong reasoning areas
   - Effective problem-solving approaches

3. **Knowledge Gaps**:
   - Misconceptions detected
   - Areas of confusion or uncertainty
   - Systematic error patterns

4. **Learning Patterns**:
   - Question types most/least successful
   - Reasoning vs. recall performance
   - Application vs. theory understanding

5. **Recommendations**:
   - Priority topics for review
   - Learning strategies to try
   - Next assessment focus areas
   - Difficulty adjustments needed

6. **Motivation Elements**:
   - Progress recognition
   - Achievement highlights
   - Encouragement for growth areas

Provide specific, actionable insights that help guide next learning steps.
"""
            return analysis_prompt
        
        def provide_feedback(question: str, student_answer: str, correct_answer: str, learning_objective: str) -> str:
            """Provide detailed feedback on a specific question response.
            
            Args:
                question: The assessment question asked
                student_answer: What the student responded
                correct_answer: The correct answer
                learning_objective: What the question was meant to assess
            
            Returns:
                Constructive feedback on the response
            """
            feedback_prompt = f"""
Provide feedback on this student response:

Question: {question}
Student Answer: {student_answer}
Correct Answer: {correct_answer}
Learning Objective: {learning_objective}

Generate constructive feedback that includes:

1. **Correctness Assessment**:
   - Whether answer is correct, partially correct, or incorrect
   - Specific aspects that are right/wrong

2. **Understanding Evaluation**:
   - Evidence of conceptual understanding
   - Areas where understanding seems unclear

3. **Strengths Recognition**:
   - Good reasoning or approaches shown
   - Partial credit for correct elements

4. **Improvement Guidance**:
   - Specific suggestions for better answers
   - Conceptual clarifications needed
   - Common misconceptions to address

5. **Learning Connections**:
   - How this connects to broader learning goals
   - Related concepts to review or explore

6. **Encouragement**:
   - Positive reinforcement for efforts
   - Growth-oriented language
   - Confidence building elements

Make feedback specific, actionable, and encouraging while maintaining accuracy about performance.
"""
            return feedback_prompt
        
        def identify_gaps(performance_data: Dict[str, Any], curriculum_area: str) -> str:
            """Identify learning gaps from assessment data.
            
            Args:
                performance_data: Student performance across multiple assessments
                curriculum_area: Area of study being analyzed
            
            Returns:
                Learning gap analysis with targeted recommendations
            """
            data_str = str(performance_data)
            gaps_prompt = f"""
Identify learning gaps in {curriculum_area} based on performance data:

Performance Data: {data_str}

Conduct learning gap analysis with:

1. **Gap Identification**:
   - Fundamental concept gaps
   - Skill application weaknesses
   - Knowledge integration issues
   - Procedural vs. conceptual gaps

2. **Priority Ranking**:
   - Most critical gaps to address first
   - Prerequisites vs. advanced concept gaps
   - High-impact gaps for overall understanding

3. **Root Cause Analysis**:
   - Why these gaps might exist
   - Common misconception patterns
   - Possible learning style mismatches

4. **Intervention Strategies**:
   - Specific learning activities to address gaps
   - Alternative explanation approaches
   - Practice exercises and resources
   - Assessment modifications if needed

5. **Progress Monitoring**:
   - How to track gap-closing progress
   - Indicators of improvement
   - Timeline for reassessment

6. **Prevention Strategies**:
   - How to prevent similar gaps in future topics
   - Early warning signs to watch for
   - Proactive support mechanisms

Focus on actionable, specific recommendations that directly address identified learning needs.
"""
            return gaps_prompt
        
        def track_progress(historical_performance: List[Dict[str, Any]], time_period: str) -> str:
            """Track learning progress over time.
            
            Args:
                historical_performance: Performance data over time
                time_period: Time span being analyzed (e.g., "last month", "full course")
            
            Returns:
                Progress analysis with trends and projections
            """
            history_str = str(historical_performance)
            progress_prompt = f"""
Track learning progress over {time_period}:

Historical Performance: {history_str}

Generate progress analysis with:

1. **Performance Trends**:
   - Overall score trajectory
   - Consistency patterns
   - Improvement/decline areas
   - Difficulty adaptation responses

2. **Skill Development**:
   - Competency growth in specific areas
   - Transfer of learning between topics
   - Mastery progression indicators

3. **Learning Velocity**:
   - Rate of concept acquisition
   - Time-to-mastery for different topics
   - Acceleration or deceleration patterns

4. **Engagement Indicators**:
   - Assessment completion rates
   - Response quality trends
   - Challenge-seeking behaviors

5. **Milestone Achievement**:
   - Learning objectives met
   - Skill benchmarks reached
   - Knowledge integration successes

6. **Future Projections**:
   - Expected performance trajectory
   - Readiness for advanced topics
   - Optimal pacing recommendations

7. **Success Factors**:
   - What approaches are working well
   - Optimal learning conditions identified
   - Effective motivation strategies

Provide both quantitative trends and qualitative insights about learning development.
"""
            return progress_prompt
        
        def recommend_practice(weak_areas: List[str], learning_style: str, available_time: str = "moderate") -> str:
            """Recommend targeted practice for improvement.
            
            Args:
                weak_areas: Areas needing additional practice
                learning_style: Student's preferred learning approach
                available_time: Time available for practice
            
            Returns:
                Personalized practice recommendations
            """
            areas_str = ", ".join(weak_areas)
            practice_prompt = f"""
Recommend targeted practice for improvement in: {areas_str}

Student Profile:
- Learning Style: {learning_style}
- Available Time: {available_time}

Design practice recommendations with:

1. **Priority Practice Areas**:
   - Most important concepts to strengthen
   - Foundational skills to reinforce
   - Application areas needing work

2. **Practice Activities**:
   - Specific exercises for each weak area
   - Variety of practice formats
   - Progressive difficulty sequences

3. **Learning Resources**:
   - Interactive exercises and simulations
   - Practice problem sets
   - Conceptual review materials
   - Video explanations or tutorials

4. **Practice Schedule**:
   - Recommended frequency and duration
   - Spaced repetition timing
   - Review and reinforcement cycles

5. **Success Indicators**:
   - How to know practice is working
   - Self-assessment checkpoints
   - Ready-for-reassessment signs

6. **Motivation Strategies**:
   - Ways to maintain engagement
   - Progress celebration milestones
   - Challenge level adjustments

7. **Integration Opportunities**:
   - Connecting practice to real applications
   - Project-based practice options
   - Collaborative learning possibilities

Ensure recommendations match learning style and time constraints while maximizing improvement potential.
"""
            return practice_prompt
        
        # Return list of tools
        return [
            create_quiz,
            design_project_assessment,
            analyze_performance,
            provide_feedback,
            identify_gaps,
            track_progress,
            recommend_practice
        ]
    
    async def create_assessment(self, topic: str, difficulty: int = 5, question_count: int = 5, objectives: List[str] = None) -> str:
        """Create a comprehensive assessment for a topic.
        
        Args:
            topic: Topic to assess
            difficulty: Difficulty level 1-10
            question_count: Number of questions
            objectives: Specific learning objectives to assess
            
        Returns:
            Complete assessment with questions and rubric
        """
        task = f"""Create a comprehensive assessment for {topic}.

Parameters:
- Difficulty Level: {difficulty}/10
- Question Count: {question_count}
- Learning Objectives: {objectives or 'general understanding'}

Use your create_quiz tool to generate an effective assessment that measures true understanding of the topic."""

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
            return f"Error creating assessment: {str(e)}"
    
    async def evaluate_performance(self, student_responses: List[Dict[str, Any]], topic: str) -> str:
        """Evaluate student performance and provide insights.
        
        Args:
            student_responses: Student's responses to assessment questions
            topic: Topic that was assessed
            
        Returns:
            Performance analysis with feedback and recommendations
        """
        task = f"""Evaluate student performance on {topic} assessment.

Student Responses: {student_responses}

Use your analyze_performance tool to provide comprehensive performance analysis with actionable insights and recommendations."""

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
            return f"Error evaluating performance: {str(e)}"
    
    async def give_feedback(self, question: str, student_answer: str, correct_answer: str, objective: str) -> str:
        """Provide detailed feedback on a specific question response.
        
        Args:
            question: The question asked
            student_answer: Student's response
            correct_answer: The correct answer
            objective: Learning objective being assessed
            
        Returns:
            Detailed, constructive feedback
        """
        task = f"""Provide feedback on this student response:

Question: {question}
Student Answer: {student_answer}
Correct Answer: {correct_answer}
Learning Objective: {objective}

Use your provide_feedback tool to give constructive, specific feedback that helps the student learn."""

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
            return f"Error providing feedback: {str(e)}"
    
    async def analyze_learning_gaps(self, performance_data: Dict[str, Any], curriculum_area: str) -> str:
        """Analyze learning gaps and recommend interventions.
        
        Args:
            performance_data: Student performance data
            curriculum_area: Area of curriculum being analyzed
            
        Returns:
            Learning gap analysis with intervention recommendations
        """
        task = f"""Analyze learning gaps in {curriculum_area}.

Performance Data: {performance_data}

Use your identify_gaps tool to find knowledge gaps and provide targeted recommendations for addressing them."""

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
            return f"Error analyzing gaps: {str(e)}"
    
    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()