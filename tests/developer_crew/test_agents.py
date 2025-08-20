"""Tests for developer_crew agents module."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add developer_crew to path for testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "developer_crew"))

from developer_crew.agents import CoderAgent, CodeReviewerAgent, QA_TesterAgent


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing."""
    mock_client = Mock()
    mock_client.create = AsyncMock(return_value=Mock(
        choices=[Mock(
            message=Mock(
                content="Test response",
                tool_calls=None
            )
        )],
        usage=Mock(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30
        )
    ))
    return mock_client


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


class TestCoderAgent:
    """Test CoderAgent functionality."""
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    def test_coder_agent_initialization(self, mock_client_class):
        """Test CoderAgent initialization."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        agent = CoderAgent(model="gpt-4", api_key="test-key")
        
        assert agent.model == "gpt-4"
        assert agent.working_directory == os.getcwd()
        assert len(agent.tools) > 0
        assert agent.agent is not None
        mock_client_class.assert_called_once_with(model="gpt-4", api_key="test-key")
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    def test_coder_agent_with_working_directory(self, mock_client_class):
        """Test CoderAgent with custom working directory."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = CoderAgent(working_directory=temp_dir)
            assert agent.working_directory == temp_dir
    
    def test_coder_tools_creation(self):
        """Test that CoderAgent creates the correct tools."""
        with patch('developer_crew.agents.OpenAIChatCompletionClient'):
            agent = CoderAgent()
            
            # Check that all expected tools are created
            tool_names = [tool.name for tool in agent.tools]
            expected_tools = [
                "read_file", "write_file", "edit_file", 
                "list_files", "get_project_structure"
            ]
            
            for expected_tool in expected_tools:
                assert expected_tool in tool_names
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    @pytest.mark.asyncio
    async def test_coder_run_task(self, mock_client_class):
        """Test CoderAgent task execution."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock the agent's run method
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=Mock(
            chat_message=Mock(content="Task completed successfully")
        ))
        
        agent = CoderAgent()
        agent.agent = mock_agent
        
        result = await agent.run("Create a simple function")
        
        assert "Task completed successfully" in result
        mock_agent.run.assert_called_once()


class TestCodeReviewerAgent:
    """Test CodeReviewerAgent functionality."""
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    def test_code_reviewer_initialization(self, mock_client_class):
        """Test CodeReviewerAgent initialization."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        agent = CodeReviewerAgent(model="gpt-3.5-turbo", api_key="test-key")
        
        assert agent.model == "gpt-3.5-turbo"
        assert agent.working_directory == os.getcwd()
        assert len(agent.tools) > 0
        assert agent.agent is not None
    
    def test_code_reviewer_tools_creation(self):
        """Test that CodeReviewerAgent creates read-only tools."""
        with patch('developer_crew.agents.OpenAIChatCompletionClient'):
            agent = CodeReviewerAgent()
            
            # Check that only read-only tools are created
            tool_names = [tool.name for tool in agent.tools]
            expected_tools = ["read_file", "list_files", "get_project_structure"]
            
            for expected_tool in expected_tools:
                assert expected_tool in tool_names
            
            # Ensure write tools are not included
            write_tools = ["write_file", "edit_file"]
            for write_tool in write_tools:
                assert write_tool not in tool_names
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    @pytest.mark.asyncio
    async def test_code_reviewer_review(self, mock_client_class):
        """Test CodeReviewerAgent review functionality."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock the agent's run method
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=Mock(
            chat_message=Mock(content="Code review completed")
        ))
        
        agent = CodeReviewerAgent()
        agent.agent = mock_agent
        
        result = await agent.review("path/to/file.py")
        
        assert "Code review completed" in result
        mock_agent.run.assert_called_once()


class TestQA_TesterAgent:
    """Test QA_TesterAgent functionality."""
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    def test_qa_tester_initialization(self, mock_client_class):
        """Test QA_TesterAgent initialization."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        agent = QA_TesterAgent(model="gpt-4", api_key="test-key")
        
        assert agent.model == "gpt-4"
        assert agent.working_directory == os.getcwd()
        assert len(agent.tools) > 0
        assert agent.agent is not None
    
    def test_qa_tester_tools_creation(self):
        """Test that QA_TesterAgent creates all necessary tools."""
        with patch('developer_crew.agents.OpenAIChatCompletionClient'):
            agent = QA_TesterAgent()
            
            # Check that all expected tools are created
            tool_names = [tool.name for tool in agent.tools]
            expected_tools = [
                "read_file", "list_files", "get_project_structure",
                "execute_command", "run_python_script", "run_tests", "check_code_quality"
            ]
            
            for expected_tool in expected_tools:
                assert expected_tool in tool_names
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    @pytest.mark.asyncio
    async def test_qa_tester_test(self, mock_client_class):
        """Test QA_TesterAgent test functionality."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock the agent's run method
        mock_agent = Mock()
        mock_agent.run = AsyncMock(return_value=Mock(
            chat_message=Mock(content="Testing completed successfully")
        ))
        
        agent = QA_TesterAgent()
        agent.agent = mock_agent
        
        result = await agent.test("path/to/test", ".")
        
        assert "Testing completed successfully" in result
        mock_agent.run.assert_called_once()


class TestAgentIntegration:
    """Test agent integration scenarios."""
    
    @patch('developer_crew.agents.OpenAIChatCompletionClient')
    def test_all_agents_can_be_created(self, mock_client_class):
        """Test that all agents can be instantiated together."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        coder = CoderAgent()
        reviewer = CodeReviewerAgent()
        tester = QA_TesterAgent()
        
        assert coder is not None
        assert reviewer is not None
        assert tester is not None
        
        # Verify they have different tool sets
        coder_tools = {tool.name for tool in coder.tools}
        reviewer_tools = {tool.name for tool in reviewer.tools}
        tester_tools = {tool.name for tool in tester.tools}
        
        # Coder should have write capabilities
        assert "write_file" in coder_tools
        assert "edit_file" in coder_tools
        
        # Reviewer should not have write capabilities
        assert "write_file" not in reviewer_tools
        assert "edit_file" not in reviewer_tools
        
        # Tester should have execution capabilities
        assert "execute_command" in tester_tools
        assert "run_tests" in tester_tools
    
    def test_agent_tool_isolation(self):
        """Test that agents have appropriate tool isolation."""
        with patch('developer_crew.agents.OpenAIChatCompletionClient'):
            coder = CoderAgent()
            reviewer = CodeReviewerAgent()
            tester = QA_TesterAgent()
            
            # Get tool names
            coder_tools = {tool.name for tool in coder.tools}
            reviewer_tools = {tool.name for tool in reviewer.tools}
            tester_tools = {tool.name for tool in tester.tools}
            
            # Common read tools should be available to all
            common_read_tools = {"read_file", "list_files", "get_project_structure"}
            assert common_read_tools.issubset(coder_tools)
            assert common_read_tools.issubset(reviewer_tools)
            assert common_read_tools.issubset(tester_tools)
            
            # Write tools should only be available to coder
            write_tools = {"write_file", "edit_file"}
            assert write_tools.issubset(coder_tools)
            assert not write_tools.intersection(reviewer_tools)
            assert not write_tools.intersection(tester_tools)
            
            # Execution tools should only be available to tester
            exec_tools = {"execute_command", "run_python_script", "run_tests", "check_code_quality"}
            assert not exec_tools.intersection(coder_tools)
            assert not exec_tools.intersection(reviewer_tools)
            assert exec_tools.issubset(tester_tools)


if __name__ == "__main__":
    pytest.main([__file__])