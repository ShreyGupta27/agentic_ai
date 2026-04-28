import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestTavilySearch:
    """Test Tavily search integration"""
    
    @patch('main.tavily')
    def test_tavily_search_success(self, mock_tavily_client):
        """Test successful Tavily search"""
        from main import tavily_search
        
        # Mock the search response
        mock_tavily_client.search.return_value = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Content 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Content 2"}
            ]
        }
        
        results = tavily_search("test query", max_results=5)
        
        assert len(results) == 2
        assert results[0]["title"] == "Result 1"
        mock_tavily_client.search.assert_called_once_with(query="test query", max_results=5)
    
    @patch('main.tavily')
    def test_tavily_search_empty_results(self, mock_tavily_client):
        """Test Tavily search with no results"""
        from main import tavily_search
        
        mock_tavily_client.search.return_value = {"results": []}
        
        results = tavily_search("obscure query")
        
        assert results == []
    
    @patch('main.tavily')
    def test_tavily_search_api_error(self, mock_tavily_client):
        """Test Tavily search with API error"""
        from main import tavily_search
        
        mock_tavily_client.search.side_effect = Exception("API Error")
        
        with pytest.raises(Exception, match="API Error"):
            tavily_search("test query")


class TestEmailSending:
    """Test email sending functionality"""
    
    @patch('main.smtplib.SMTP_SSL')
    def test_send_email_success(self, mock_smtp):
        """Test successful email sending"""
        from main import send_email
        
        # Mock SMTP connection
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        result = send_email("test@example.com", "Test Subject", "Test Body")
        
        assert "Email sent" in result
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()
    
    @patch('main.smtplib.SMTP_SSL')
    def test_send_email_auth_failure(self, mock_smtp):
        """Test email sending with authentication failure"""
        from main import send_email
        import smtplib
        
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, "Authentication failed")
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        with pytest.raises(smtplib.SMTPAuthenticationError):
            send_email("test@example.com", "Test", "Body")
    
    @patch('main.smtplib.SMTP_SSL')
    def test_send_email_connection_error(self, mock_smtp):
        """Test email sending with connection error"""
        from main import send_email
        
        mock_smtp.side_effect = Exception("Connection failed")
        
        with pytest.raises(Exception, match="Connection failed"):
            send_email("test@example.com", "Test", "Body")


class TestGeminiIntegration:
    """Test Gemini AI integration"""
    
    @patch('main.genai.GenerativeModel')
    def test_summarize_text_success(self, mock_model_class):
        """Test successful text summarization"""
        from main import summarize_text
        
        # Mock Gemini response
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "This is a summary"
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model
        
        result = summarize_text("Long text here", topic_hint="test topic")
        
        assert result == "This is a summary"
        mock_model.generate_content.assert_called_once()
    
    @patch('main.genai.GenerativeModel')
    def test_summarize_text_empty_response(self, mock_model_class):
        """Test summarization with empty response"""
        from main import summarize_text
        
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = None
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model
        
        result = summarize_text("Text")
        
        assert result == ""
    
    @patch('main.genai.GenerativeModel')
    def test_generate_tasks_success(self, mock_model_class):
        """Test successful task generation"""
        from main import generate_tasks
        
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '''```json
        {
            "tasks": [
                {"action": "web_search", "query": "test query"},
                {"action": "send_email", "to_email": "test@example.com", "subject": "Test", "body": "Body"}
            ]
        }
        ```'''
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model
        
        task_list = generate_tasks("Search for test and email results")
        
        assert len(task_list.tasks) == 2
        assert task_list.tasks[0].action == "web_search"
        assert task_list.tasks[1].action == "send_email"
    
    @patch('main.genai.GenerativeModel')
    def test_generate_tasks_invalid_json(self, mock_model_class):
        """Test task generation with invalid JSON"""
        from main import generate_tasks
        
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "This is not JSON"
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model
        
        task_list = generate_tasks("Do something")
        
        assert len(task_list.tasks) == 0


class TestTaskExecution:
    """Test task execution orchestration"""
    
    @patch('main.do_web_search_task')
    @patch('main.do_send_email_task')
    def test_execute_task_list_success(self, mock_email, mock_search):
        """Test successful execution of task list"""
        from main import execute_task_list, TaskList, Task
        
        mock_search.return_value = "Search results"
        mock_email.return_value = "Email sent"
        
        tasks = TaskList(tasks=[
            Task(action="web_search", query="test"),
            Task(action="send_email", to_email="test@example.com")
        ])
        
        execute_task_list(tasks)
        
        mock_search.assert_called_once()
        mock_email.assert_called_once()
    
    def test_execute_task_list_empty(self):
        """Test execution with empty task list"""
        from main import execute_task_list, TaskList
        
        tasks = TaskList(tasks=[])
        
        # Should not raise any errors
        execute_task_list(tasks)
    
    @patch('main.do_web_search_task')
    def test_execute_task_list_with_error(self, mock_search):
        """Test execution continues after task error"""
        from main import execute_task_list, TaskList, Task
        
        mock_search.side_effect = Exception("Task failed")
        
        tasks = TaskList(tasks=[
            Task(action="web_search", query="test")
        ])
        
        # Should not raise, just log the error
        execute_task_list(tasks)
        
        mock_search.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
