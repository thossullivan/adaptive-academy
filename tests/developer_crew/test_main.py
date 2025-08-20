"""Tests for developer_crew main CLI module."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typer.testing import CliRunner

# Add developer_crew to path for testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "developer_crew"))

from developer_crew.main import app, check_api_key


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


class TestCLICommands:
    """Test CLI command functionality."""
    
    def test_cli_app_exists(self):
        """Test that the CLI app is properly configured."""
        assert app is not None
        assert hasattr(app, 'command')
    
    def test_init_command(self, runner, temp_workspace):
        """Test the init command."""
        with patch('developer_crew.main.os.getcwd', return_value=temp_workspace):
            result = runner.invoke(app, ['init'])
            
            # Should succeed
            assert result.exit_code == 0
            
            # Should create .env file
            env_file = Path(temp_workspace) / '.env'
            assert env_file.exists()
            
            # Should contain OpenAI API key placeholder
            content = env_file.read_text()
            assert 'OPENAI_API_KEY=' in content
    
    def test_init_command_env_exists(self, runner, temp_workspace):
        """Test init command when .env already exists."""
        # Create existing .env file
        env_file = Path(temp_workspace) / '.env'
        env_file.write_text('EXISTING_KEY=value\n')
        
        with patch('developer_crew.main.os.getcwd', return_value=temp_workspace):
            result = runner.invoke(app, ['init'])
            
            # Should still succeed
            assert result.exit_code == 0
            
            # Should preserve existing content
            content = env_file.read_text()
            assert 'EXISTING_KEY=value' in content
            assert 'OPENAI_API_KEY=' in content
    
    @patch('developer_crew.main.CoderAgent')
    def test_code_command(self, mock_coder_class, runner):
        """Test the code command."""
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agent
            mock_agent = Mock()
            mock_agent.run = AsyncMock(return_value="Code generated successfully")
            mock_agent.close = AsyncMock()
            mock_coder_class.return_value = mock_agent
            
            result = runner.invoke(app, ['code', 'Create a hello world function'])
            
            # Should succeed
            assert result.exit_code == 0
            mock_coder_class.assert_called_once()
    
    @patch('developer_crew.main.CodeReviewerAgent')
    def test_review_command(self, mock_reviewer_class, runner, temp_workspace):
        """Test the review command."""
        # Create a test file
        test_file = Path(temp_workspace) / 'test.py'
        test_file.write_text('print("hello")')
        
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agent
            mock_agent = Mock()
            mock_agent.review = AsyncMock(return_value="Code review completed")
            mock_agent.close = AsyncMock()
            mock_reviewer_class.return_value = mock_agent
            
            result = runner.invoke(app, ['review', str(test_file)])
            
            # Should succeed
            assert result.exit_code == 0
            mock_reviewer_class.assert_called_once()
    
    def test_review_command_file_not_found(self, runner):
        """Test review command with non-existent file."""
        result = runner.invoke(app, ['review', '/path/that/does/not/exist.py'])
        
        # Should fail
        assert result.exit_code != 0
        assert "not found" in result.output.lower()
    
    @patch('developer_crew.main.QA_TesterAgent')
    def test_test_command(self, mock_tester_class, runner, temp_workspace):
        """Test the test command."""
        # Create a test directory
        test_dir = Path(temp_workspace) / 'tests'
        test_dir.mkdir()
        
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agent
            mock_agent = Mock()
            mock_agent.test = AsyncMock(return_value="Tests completed successfully")
            mock_agent.close = AsyncMock()
            mock_tester_class.return_value = mock_agent
            
            result = runner.invoke(app, ['test', str(test_dir)])
            
            # Should succeed
            assert result.exit_code == 0
            mock_tester_class.assert_called_once()
    
    def test_test_command_path_not_found(self, runner):
        """Test test command with non-existent path."""
        result = runner.invoke(app, ['test', '/path/that/does/not/exist'])
        
        # Should fail
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestWorkflowCommand:
    """Test the workflow command functionality."""
    
    @patch('developer_crew.main.CoderAgent')
    @patch('developer_crew.main.CodeReviewerAgent')
    @patch('developer_crew.main.QA_TesterAgent')
    def test_workflow_full_pipeline(self, mock_tester_class, 
                                   mock_reviewer_class, mock_coder_class, runner):
        """Test the full workflow pipeline."""
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agents
            mock_coder = Mock()
            mock_coder.run = AsyncMock(return_value="Code written successfully")
            mock_coder.close = AsyncMock()
            mock_coder_class.return_value = mock_coder
            
            mock_reviewer = Mock()
            mock_reviewer_agent = Mock()
            mock_reviewer_agent.run = AsyncMock(return_value=Mock(chat_message=Mock(content="Code reviewed successfully")))
            mock_reviewer.agent = mock_reviewer_agent
            mock_reviewer.close = AsyncMock()
            mock_reviewer_class.return_value = mock_reviewer
            
            mock_tester = Mock()
            mock_tester.test = AsyncMock(return_value="Tests passed successfully")
            mock_tester.close = AsyncMock()
            mock_tester_class.return_value = mock_tester
            
            result = runner.invoke(app, ['workflow', 'Create a calculator function'])
            
            # Should succeed
            assert result.exit_code == 0
            
            # All agents should be created
            mock_coder_class.assert_called_once()
            mock_reviewer_class.assert_called_once()
            mock_tester_class.assert_called_once()
    
    @patch('developer_crew.main.CoderAgent')
    @patch('developer_crew.main.QA_TesterAgent')
    def test_workflow_skip_review(self, mock_tester_class, mock_coder_class, runner):
        """Test workflow with review skipped."""
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agents
            mock_coder = Mock()
            mock_coder.run = AsyncMock(return_value="Code written successfully")
            mock_coder.close = AsyncMock()
            mock_coder_class.return_value = mock_coder
            
            mock_tester = Mock()
            mock_tester.test = AsyncMock(return_value="Tests passed successfully")
            mock_tester.close = AsyncMock()
            mock_tester_class.return_value = mock_tester
            
            with patch('developer_crew.main.CodeReviewerAgent') as mock_reviewer_class:
                result = runner.invoke(app, ['workflow', 'Create a function', '--skip-review'])
                
                # Should succeed
                assert result.exit_code == 0
                
                # Coder and tester should be created, but not reviewer
                mock_coder_class.assert_called_once()
                mock_reviewer_class.assert_not_called()
                mock_tester_class.assert_called_once()


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_check_api_key_present(self):
        """Test checking API key when present."""
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            result = check_api_key()
            assert result is True
    
    def test_check_api_key_missing(self):
        """Test checking API key when missing."""
        with patch('developer_crew.main.os.getenv', return_value=None):
            result = check_api_key()
            assert result is False


class TestCLIErrorHandling:
    """Test CLI error handling scenarios."""
    
    def test_missing_api_key(self, runner):
        """Test behavior when API key is missing."""
        with patch('developer_crew.main.os.getenv', return_value=None):
            result = runner.invoke(app, ['code', 'test task'])
            
            # Should exit with error
            assert result.exit_code != 0
    
    @patch('developer_crew.main.CoderAgent')
    def test_agent_creation_failure(self, mock_coder_class, runner):
        """Test behavior when agent creation fails."""
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agent creation failure
            mock_coder_class.side_effect = Exception("Agent creation failed")
            
            result = runner.invoke(app, ['code', 'test task'])
            
            # Should handle error gracefully
            assert result.exit_code != 0
    
    @patch('developer_crew.main.CoderAgent')
    def test_task_execution_failure(self, mock_coder_class, runner):
        """Test behavior when task execution fails."""
        # Mock API key check to pass
        with patch('developer_crew.main.os.getenv', return_value='test-key'):
            # Mock agent with failing task execution
            mock_agent = Mock()
            mock_agent.run = AsyncMock(side_effect=Exception("Task failed"))
            mock_agent.close = AsyncMock()
            mock_coder_class.return_value = mock_agent
            
            result = runner.invoke(app, ['code', 'test task'])
            
            # Should handle error gracefully
            assert result.exit_code != 0


if __name__ == "__main__":
    pytest.main([__file__])