# 🤖 Agentic AI Assistant

An intelligent AI agent that converts natural language requests into executable tasks using Google Gemini, Tavily search, and Gmail integration.

## 🌟 Overview

This project demonstrates an agentic AI system that:
- Parses natural language requests using Google's Gemini AI
- Breaks down complex requests into structured task chains
- Executes tasks autonomously (web search, email sending)
- Chains task outputs (e.g., search results → email body)
- Handles errors gracefully with comprehensive logging

## 🏗️ Architecture

User Input → Gemini (Task Planning) → Task Executor → Tools (Search/Email)
                                            ↓
                                    Memory & State Management

**Components:**
- **Task Planner**: Uses Gemini to convert natural language to structured JSON tasks
- **Task Executor**: Orchestrates task execution with shared memory context
- **Tools**: Modular integrations (Tavily search, Gmail SMTP)
- **State Management**: Tracks execution history and intermediate results

## ✨ Features

- **Natural Language Interface**: Describe what you want in plain English
- **Multi-Tool Integration**: Web search (Tavily) and email (Gmail)
- **Task Chaining**: Automatically passes data between tasks
- **Smart Summarization**: Condenses long search results using Gemini
- **Error Handling**: Robust retry logic and graceful degradation
- **Logging**: Comprehensive logging for debugging and monitoring

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- Google Gemini API key
- Tavily API key
- Gmail account with App Password

## 🔧 Configuration

The agent uses these environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `TAVILY_API_KEY` | Tavily search API key | Yes |
| `EMAIL_ADDRESS` | Gmail address for sending | Yes |
| `EMAIL_APP_PASSWORD` | Gmail app password | Yes |

## 📊 Example Workflows

### Workflow 1: Research & Email
```
Input: "Find the top 5 AI conferences in 2024 and email them to me"

Tasks Generated:
1. web_search(query="top AI conferences 2024")
2. send_email(to_email="your@email.com", subject="Top AI Conferences", body="[search results]")
```

### Workflow 2: Information Gathering
```
Input: "Search for Python best practices"

Tasks Generated:
1. web_search(query="Python best practices")
```

## 🛠️ Technical Highlights

- **Pydantic Models**: Type-safe task definitions
- **Error Recovery**: Automatic retry with exponential backoff
- **Structured Logging**: JSON-formatted logs for production monitoring
- **Modular Design**: Easy to add new tools and capabilities
- **Memory Context**: Tasks share state for complex workflows

## 📝 License

Copyright (c) 2026 Shrey Gupta. All rights reserved.

Unauthorized copying, modification, or distribution of this software, via any medium, is strictly prohibited.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## 👤 Author

Shrey Gupta - [GitHub](https://github.com/ShreyGupta27)

## Acknowledgments

- Google Gemini for AI capabilities
- Tavily for web search API
- The open-source community
