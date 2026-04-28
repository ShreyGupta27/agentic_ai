import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from pydantic import ValidationError
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import (
    Task, TaskList, extract_json_from_text, format_search_results,
    do_web_search_task, do_send_email_task
)


class TestTaskModels:
    """Test Pydantic task models"""
    
    def test_task_creation_with_params(self):
        """Test creating a task with action and params"""
        task = Task(action="web_search", query="test query")
        assert task.action == "web_search"
        assert task.params == {"query": "test query"}
    
    def test_task_creation_minimal(self):
        """Test creating a task with just action"""
        task = Task(action="test_action")
        assert task.action == "test_action"
        assert task.params == {}
    
    def test_task_list_creation(self):
        """Test creating a task list"""
        tasks = TaskList(tasks=[
            Task(action="web_search", query="test"),
            Task(action="send_email", to_email="test@example.com")
        ])
        assert len(tasks.tasks) == 2
        assert tasks.tasks[0].action == "web_search"
        assert tasks.tasks[1].action == "send_email"


class TestJSONExtraction:
    """Test JSON extraction from Gemini responses"""
    
    def test_extract_json_plain(self):
        """Test extracting plain JSON"""
        text = '{"tasks": [{"action": "test"}]}'
        result = extract_json_from_text(text)
        assert result == '{"tasks": [{"action": "test"}]}'
    
    def test_extract_json_with_markdown(self):
        """Test extracting JSON wrapped in markdown"""
        text = '```json\n{"tasks": [{"action": "test"}]}\n```'
        result = extract_json_from_text(text)
        assert result == '{"tasks": [{"action": "test"}]}'
    
    def test_extract_json_with_markdown_no_lang(self):
        """Test extracting JSON wrapped in markdown without language"""
        text = '```\n{"tasks": [{"action": "test"}]}\n```'
        result = extract_json_from_text(text)
        assert result == '{"tasks": [{"action": "test"}]}'
    
    def test_extract_json_empty(self):
        """Test extracting from empty string"""
        result = extract_json_from_text("")
        assert result == ""
    
    def test_extract_json_none(self):
        """Test extracting from None"""
        result = extract_json_from_text(None)
        assert result == ""


class TestSearchResultsFormatting:
    """Test search results formatting"""
    
    def test_format_search_results_basic(self):
        """Test formatting basic search results"""
        results = [
            {"title": "Test 1", "url": "https://example.com/1", "content": "Content 1"},
            {"title": "Test 2", "url": "https://example.com/2", "content": "Content 2"}
        ]
        formatted = format_search_results(results)
        assert "Test 1" in formatted
        assert "https://example.com/1" in formatted
        assert "Content 1" in formatted
        assert "Test 2" in formatted
    
    def test_format_search_results_empty(self):
        """Test formatting empty results"""
        formatted = format_search_results([])
        assert formatted == "No search results found."
    
    def test_format_search_results_missing_fields(self):
        """Test formatting results with missing fields"""
        results = [{"title": "Test"}]
        formatted = format_search_results(results)
        assert "Test" in formatted
        assert "No title" not in formatted


class TestWebSearchTask:
    """Test web search task execution"""
    
    @patch('main.tavily_search')
    @patch('main.summarize_text')
    def test_web_search_with_summarization(self, mock_summarize, mock_search):
        """Test web search that triggers summarization"""
        # Setup mocks
        mock_search.return_value = [
            {"title": "Test", "url": "https://example.com", "content": "x" * 700}
        ]
        mock_summarize.return_value = "Summary of results"
        
        memory = {}
        params = {"query": "test query"}
        
        result = do_web_search_task(params, memory)
        
        assert result == "Summary of results"
        assert memory["last_search_summary"] == "Summary of results"
        mock_search.assert_called_once_with("test query")
        mock_summarize.assert_called_once()
    
    @patch('main.tavily_search')
    def test_web_search_without_summarization(self, mock_search):
        """Test web search with short results (no summarization)"""
        mock_search.return_value = [
            {"title": "Test", "url": "https://example.com", "content": "Short"}
        ]
        
        memory = {}
        params = {"query": "test"}
        
        result = do_web_search_task(params, memory)
        
        assert "Test" in result
        assert memory["last_search_summary"] == result
    
    def test_web_search_missing_query(self):
        """Test web search with missing query"""
        memory = {}
        params = {}
        
        result = do_web_search_task(params, memory)
        
        assert "Missing query" in result


class TestSendEmailTask:
    """Test send email task execution"""
    
    @patch('main.send_email')
    def test_send_email_basic(self, mock_send):
        """Test basic email sending"""
        mock_send.return_value = "✅ Email sent to test@example.com"
        
        memory = {}
        params = {
            "to_email": "test@example.com",
            "subject": "Test",
            "body": "Test body"
        }
        
        result = do_send_email_task(params, memory)
        
        assert "Email sent" in result
        mock_send.assert_called_once_with("test@example.com", "Test", "Test body")
    
    @patch('main.send_email')
    def test_send_email_with_search_results(self, mock_send):
        """Test email with search results placeholder"""
        mock_send.return_value = "✅ Email sent"
        
        memory = {"last_search_summary": "Search results here"}
        params = {
            "to_email": "test@example.com",
            "subject": "Test",
            "body": "[Insert Web Search Results Here]"
        }
        
        result = do_send_email_task(params, memory)
        
        # Check that send_email was called with replaced body
        call_args = mock_send.call_args[0]
        assert "Search results here" in call_args[2]
    
    def test_send_email_missing_recipient(self):
        """Test email with missing recipient"""
        memory = {}
        params = {"subject": "Test", "body": "Test"}
        
        result = do_send_email_task(params, memory)
        
        assert "Missing recipient" in result
    
    @patch('main.send_email')
    def test_send_email_empty_body_uses_search(self, mock_send):
        """Test email with empty body uses search results"""
        mock_send.return_value = "✅ Email sent"
        
        memory = {"last_search_summary": "Auto-filled content"}
        params = {
            "to_email": "test@example.com",
            "subject": "Test",
            "body": ""
        }
        
        result = do_send_email_task(params, memory)
        
        call_args = mock_send.call_args[0]
        assert call_args[2] == "Auto-filled content"


class TestRetryDecorator:
    """Test retry with backoff decorator"""
    
    @patch('main.time.sleep')
    def test_retry_success_first_attempt(self, mock_sleep):
        """Test function succeeds on first attempt"""
        from main import retry_with_backoff
        
        @retry_with_backoff(max_retries=3, delay=1)
        def success_func():
            return "success"
        
        result = success_func()
        assert result == "success"
        mock_sleep.assert_not_called()
    
    @patch('main.time.sleep')
    def test_retry_success_after_failures(self, mock_sleep):
        """Test function succeeds after retries"""
        from main import retry_with_backoff
        
        call_count = 0
        
        @retry_with_backoff(max_retries=3, delay=1)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        result = flaky_func()
        assert result == "success"
        assert call_count == 3
        assert mock_sleep.call_count == 2  # Slept twice before success
    
    @patch('main.time.sleep')
    def test_retry_exhausted(self, mock_sleep):
        """Test function fails after max retries"""
        from main import retry_with_backoff
        
        @retry_with_backoff(max_retries=2, delay=1)
        def always_fails():
            raise ValueError("Always fails")
        
        with pytest.raises(ValueError, match="Always fails"):
            always_fails()
        
        assert mock_sleep.call_count == 1  # Slept once before final failure


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
