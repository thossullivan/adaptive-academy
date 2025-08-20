"""TutorAgent for personalized learning instruction and explanations."""

import asyncio
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.messages import TextMessage, ChatMessage
from autogen_agentchat.base import Response


class TutorAgent:
    """AI agent specialized in personalized learning instruction and explanations.
    
    This agent provides:
    - Concept explanations tailored to user's learning style
    - Interactive teaching and answering questions
    - Physics analogies for AI/ML concepts
    - Adaptive teaching based on user understanding
    """
    
    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        """Initialize the Tutor agent.
        
        Args:
            model: OpenAI model to use (default: gpt-4)
            api_key: OpenAI API key (if not provided, will use environment variable)
        """
        self.model_client = OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
        
        system_message = """You are an expert AI/ML tutor with a PhD in both Computer Science and Physics. Your specialty is making complex AI and machine learning concepts accessible through personalized instruction.

Core Responsibilities:
- Provide clear, engaging explanations of AI/ML concepts
- Adapt teaching style to user's learning preferences and background
- Use physics analogies when helpful (your specialty!)
- Answer user questions with patience and clarity
- Break down complex topics into digestible pieces
- Provide practical examples and real-world applications

Teaching Philosophy:
1. Start with intuition, then add mathematical rigor
2. Use analogies and metaphors to make abstract concepts concrete
3. Connect new concepts to what the student already knows
4. Encourage questions and active learning
5. Adapt explanations based on user feedback and understanding
6. Provide multiple perspectives on the same concept

Physics Analogies Expertise:
- Use physics concepts to explain ML algorithms
- Draw parallels between mathematical ML concepts and physical phenomena
- Help students build intuition through familiar physical systems
- Examples: Neural networks as electrical circuits, gradient descent as finding lowest energy states, etc.

Available Teaching Tools:
- explain_concept: Provide detailed explanations of specific concepts
- create_analogy: Generate physics analogies for complex topics  
- answer_question: Respond to specific user questions
- assess_understanding: Check comprehension through targeted questions
- recommend_resources: Suggest additional learning materials

Communication Style:
- Patient and encouraging
- Clear and structured explanations
- Use examples and analogies liberally
- Ask questions to gauge understanding
- Provide multiple ways to think about the same concept
- Adapt complexity to user's current level"""

        # Create teaching tools
        self.tools = self._create_teaching_tools()
        
        self.agent = AssistantAgent(
            name="TutorAgent",
            model_client=self.model_client,
            system_message=system_message,
            tools=self.tools,
        )
    
    def _create_teaching_tools(self):
        """Create educational tools for the tutor agent."""
        
        def explain_concept(concept: str, user_background: str = "general", learning_style: str = "mixed", difficulty_level: int = 5) -> str:
            """Explain a concept with personalized approach.
            
            Args:
                concept: The concept to explain (e.g., "neural networks", "gradient descent")
                user_background: User's background (e.g., "physics", "software engineering", "mathematics")
                learning_style: Preferred learning style ("visual", "analytical", "hands-on", "analogies")
                difficulty_level: Complexity level 1-10 (1=beginner, 10=expert)
            
            Returns:
                Detailed explanation tailored to the user
            """
            explanation_prompt = f"""
Explain {concept} for someone with a {user_background} background who prefers {learning_style} learning at difficulty level {difficulty_level}/10.

Structure your explanation as:
1. **Intuitive Overview**: Start with the big picture and intuition
2. **Key Concepts**: Break down the main ideas
3. **Analogies**: Use physics analogies if helpful for understanding
4. **Examples**: Provide concrete, practical examples
5. **Mathematical Foundation**: Add appropriate mathematical detail for the difficulty level
6. **Common Misconceptions**: Address typical confusion points
7. **Next Steps**: What to learn next

Adapt the depth and style based on the user's background and preferences.
"""
            return explanation_prompt
        
        def create_analogy(concept: str, target_domain: str = "physics") -> str:
            """Create analogies to help understand complex concepts.
            
            Args:
                concept: The ML/AI concept to explain
                target_domain: Domain for analogies (physics, cooking, sports, etc.)
            
            Returns:
                Creative analogies that illuminate the concept
            """
            analogy_prompt = f"""
Create 2-3 analogies from {target_domain} that help explain {concept}. 

For each analogy:
1. Set up the analogy clearly
2. Map the key elements between domains
3. Explain what the analogy illuminates
4. Note any limitations of the analogy

Make the analogies intuitive and memorable while being technically accurate.
"""
            return analogy_prompt
        
        def answer_question(question: str, context: str = "", user_level: str = "intermediate") -> str:
            """Answer specific user questions about AI/ML concepts.
            
            Args:
                question: The user's question
                context: Additional context about what they're learning
                user_level: User's experience level (beginner/intermediate/advanced)
            
            Returns:
                Clear, targeted answer to the question
            """
            answer_prompt = f"""
Answer this question: "{question}"

Context: {context}
User Level: {user_level}

Provide:
1. **Direct Answer**: Address the question directly
2. **Explanation**: Why this answer is correct
3. **Examples**: Concrete examples if helpful
4. **Related Concepts**: How this connects to other topics
5. **Follow-up**: Suggest related questions they might want to explore

Adjust the technical depth for a {user_level} learner.
"""
            return answer_prompt
        
        def assess_understanding(concept: str, check_type: str = "conceptual") -> str:
            """Create questions to check student understanding.
            
            Args:
                concept: Concept to assess understanding of
                check_type: Type of assessment (conceptual, mathematical, practical)
            
            Returns:
                Questions and prompts to gauge understanding
            """
            assessment_prompt = f"""
Create {check_type} questions to check understanding of {concept}.

Provide:
1. **Quick Check**: 2-3 simple questions to verify basic understanding
2. **Deeper Understanding**: 1-2 questions that require connecting concepts
3. **Application**: 1 question about practical application
4. **Common Pitfalls**: Questions that reveal common misconceptions

Format as interactive questions the student can think about or answer.
"""
            return assessment_prompt
        
        def recommend_resources(topic: str, current_level: str, goal: str = "general understanding") -> str:
            """Recommend learning resources for continued study.
            
            Args:
                topic: The topic they want to learn more about
                current_level: Their current understanding level
                goal: What they want to achieve (understanding, implementation, research)
            
            Returns:
                Curated list of learning resources
            """
            resource_prompt = f"""
Recommend learning resources for {topic} for someone at {current_level} level with goal: {goal}.

Organize recommendations by:
1. **Next Steps**: What to learn immediately next
2. **Core Resources**: Essential books, papers, or courses
3. **Practical**: Hands-on tutorials, projects, or exercises  
4. **Advanced**: Resources for deeper/broader understanding
5. **Communities**: Forums, groups, or people to follow

Focus on high-quality, well-regarded resources in the field.
"""
            return resource_prompt
        
        # Return list of tools with proper function signatures
        return [
            explain_concept,
            create_analogy, 
            answer_question,
            assess_understanding,
            recommend_resources
        ]
    
    async def teach_concept(self, concept: str, user_context: Dict[str, Any] = None) -> str:
        """Main teaching method - explain a concept to the student.
        
        Args:
            concept: The concept to teach
            user_context: Context about the user (background, preferences, etc.)
            
        Returns:
            The tutor's explanation and teaching content
        """
        if user_context is None:
            user_context = {}
            
        background = user_context.get('background', 'general')
        learning_style = user_context.get('learning_style', 'mixed')
        difficulty = user_context.get('difficulty_level', 5)
        
        task = f"""Please explain {concept} to a student.

Student Context:
- Background: {background}
- Learning Style: {learning_style}  
- Difficulty Level: {difficulty}/10

Use your teaching tools to provide a comprehensive, personalized explanation. Start with explain_concept, then enhance with analogies if helpful."""

        try:
            response = await self.agent.run(task=task)
            if hasattr(response, 'chat_message') and response.chat_message:
                return response.chat_message.content
            elif hasattr(response, 'inner_messages') and response.inner_messages:
                # Extract content from the last message
                last_message = response.inner_messages[-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            return str(response)
        except Exception as e:
            return f"Error teaching concept: {str(e)}"
    
    async def answer_student_question(self, question: str, context: str = "", user_level: str = "intermediate") -> str:
        """Answer a specific student question.
        
        Args:
            question: The student's question
            context: Learning context or current topic
            user_level: Student's experience level
            
        Returns:
            The tutor's answer
        """
        task = f"""A student has asked: "{question}"

Context: {context}
Student Level: {user_level}

Please use your answer_question tool to provide a helpful, clear response."""

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
            return f"Error answering question: {str(e)}"
    
    async def create_physics_analogy(self, concept: str) -> str:
        """Create physics analogies for ML concepts.
        
        Args:
            concept: The ML concept to create analogies for
            
        Returns:
            Physics analogies that help explain the concept
        """
        task = f"""Create physics analogies to help explain {concept}.

Use your create_analogy tool with target_domain="physics" to generate intuitive analogies that connect this ML concept to familiar physical phenomena."""

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
            return f"Error creating analogy: {str(e)}"
    
    async def check_understanding(self, concept: str) -> str:
        """Create questions to assess student understanding.
        
        Args:
            concept: Concept to assess understanding of
            
        Returns:
            Questions to check comprehension
        """
        task = f"""Create assessment questions to check student understanding of {concept}.

Use your assess_understanding tool to generate questions that reveal how well the student grasps the concept."""

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
    
    async def close(self):
        """Close the model client connection."""
        await self.model_client.close()