import os
import re
import json
import smtplib
import logging
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, model_validator
from datetime import datetime, timedelta

# LLM + search clients
import google.generativeai as genai
from tavily import TavilyClient

# New tool imports
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GOOGLE_CALENDAR_CREDENTIALS = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "credentials.json")

if not GEMINI_API_KEY:
    logger.error("Missing GEMINI_API_KEY in .env")
    raise RuntimeError("Missing GEMINI_API_KEY in .env")
if not TAVILY_API_KEY:
    logger.error("Missing TAVILY_API_KEY in .env")
    raise RuntimeError("Missing TAVILY_API_KEY in .env")
if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
    logger.error("Missing EMAIL_ADDRESS or EMAIL_APP_PASSWORD in .env")
    raise RuntimeError("Missing EMAIL_ADDRESS or EMAIL_APP_PASSWORD in .env")

# Configure clients
try:
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_MODEL = "gemini-pro"
    tavily = TavilyClient(api_key=TAVILY_API_KEY)
    
    # Initialize Slack client if token provided
    slack_client = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None
    
    logger.info("API clients configured successfully")
except Exception as e:
    logger.error(f"Failed to configure API clients: {e}")
    raise

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Google Calendar scopes
CALENDAR_SCOPES = ['https://www.googleapis.com/auth/calendar']

# Pydantic Task models
class Task(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)

    @model_validator(mode='before')
    @classmethod
    def pack_params(cls, values):
        # Pull 'action' out and pack all other keys into params
        if isinstance(values, dict):
            action = values.pop("action", None)
            params = {k: v for k, v in values.items()}
            return {"action": action, "params": params}
        return values

class TaskList(BaseModel):
    tasks: List[Task]

# Utility: Retry decorator
def retry_with_backoff(max_retries: int = MAX_RETRIES, delay: int = RETRY_DELAY):
    """Decorator for retrying functions with exponential backoff"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
                        raise
                    wait_time = delay * (2 ** attempt)
                    logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
        return wrapper
    return decorator

# Utility: Gemini summarizer
@retry_with_backoff()
def summarize_text(text: str, topic_hint: Optional[str] = None, max_words: int = 200) -> str:
    """Summarize text using Gemini AI"""
    try:
        prompt = (
            f"Summarize the following content into a concise summary"
            f"{' (topic: ' + topic_hint + ')' if topic_hint else ''}. "
            f"Keep it under {max_words} words and produce clear bullet points or short paragraphs:\n\n"
            f"{text}"
        )
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(prompt)
        logger.info(f"Successfully summarized text (topic: {topic_hint})")
        return (resp.text or "").strip()
    except Exception as e:
        logger.error(f"Error in summarize_text: {e}")
        raise

# Tool: Tavily web search
@retry_with_backoff()
def tavily_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Returns a list of result dicts with keys usually including 'title', 'url', 'content'.
    """
    try:
        logger.info(f"Executing Tavily search: {query}")
        raw = tavily.search(query=query, max_results=max_results)
        # tavily-python may return dict; adapt safely
        results = raw.get("results", []) if isinstance(raw, dict) else []
        logger.info(f"Tavily search returned {len(results)} results")
        return results
    except Exception as e:
        logger.error(f"Tavily search failed for query '{query}': {e}")
        raise

def format_search_results(results: List[Dict[str, Any]]) -> str:
    """Create a human-friendly text block from Tavily results."""
    try:
        lines = []
        for i, r in enumerate(results, start=1):
            title = r.get("title") or r.get("name") or "No title"
            url = r.get("url") or r.get("link") or ""
            snippet = (r.get("content") or r.get("snippet") or "").strip()
            if snippet:
                snippet = snippet.replace("\n", " ").strip()
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}\n")
        result = "\n".join(lines).strip() if lines else "No search results found."
        logger.debug(f"Formatted {len(lines)} search results")
        return result
    except Exception as e:
        logger.error(f"Error formatting search results: {e}")
        return "Error formatting search results"

# Email sender (Gmail SMTP)
@retry_with_backoff(max_retries=2)
def send_email(to_email: str, subject: str, body: str) -> str:
    """Send email via Gmail SMTP"""
    try:
        logger.info(f"Sending email to {to_email} with subject: {subject}")
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Use SSL (465) which works with App Passwords
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS.strip(), EMAIL_APP_PASSWORD.strip())
            smtp.send_message(msg)
        logger.info(f"✅ Email sent successfully to {to_email}")
        return f"✅ Email sent to {to_email}"
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {e}")
        raise

# Tool: Weather (OpenWeatherMap)
@retry_with_backoff()
def get_weather(location: str, units: str = "metric") -> str:
    """Get current weather for a location using OpenWeatherMap API"""
    try:
        if not OPENWEATHER_API_KEY:
            return "❌ OpenWeatherMap API key not configured. Add OPENWEATHER_API_KEY to .env"
        
        logger.info(f"Fetching weather for: {location}")
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": location,
            "appid": OPENWEATHER_API_KEY,
            "units": units
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract relevant info
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        description = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind_speed = data["wind"]["speed"]
        
        unit_symbol = "°C" if units == "metric" else "°F"
        
        result = (
            f"🌤️ Weather in {location}:\n"
            f"Temperature: {temp}{unit_symbol} (feels like {feels_like}{unit_symbol})\n"
            f"Conditions: {description.capitalize()}\n"
            f"Humidity: {humidity}%\n"
            f"Wind Speed: {wind_speed} {'m/s' if units == 'metric' else 'mph'}"
        )
        
        logger.info(f"Weather fetched successfully for {location}")
        return result
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.error(f"Location not found: {location}")
            return f"❌ Location '{location}' not found"
        logger.error(f"Weather API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error fetching weather: {e}")
        raise

# Tool: Slack
@retry_with_backoff()
def send_slack_message(channel: str, message: str) -> str:
    """Send a message to a Slack channel"""
    try:
        if not slack_client:
            return "❌ Slack bot token not configured. Add SLACK_BOT_TOKEN to .env"
        
        logger.info(f"Sending Slack message to channel: {channel}")
        
        response = slack_client.chat_postMessage(
            channel=channel,
            text=message
        )
        
        logger.info(f"✅ Slack message sent to {channel}")
        return f"✅ Message sent to Slack channel: {channel}"
        
    except SlackApiError as e:
        error_msg = e.response.get("error", "Unknown error")
        logger.error(f"Slack API error: {error_msg}")
        if error_msg == "channel_not_found":
            return f"❌ Slack channel '{channel}' not found"
        elif error_msg == "not_in_channel":
            return f"❌ Bot not in channel '{channel}'. Invite the bot first."
        raise
    except Exception as e:
        logger.error(f"Error sending Slack message: {e}")
        raise

# Tool: Google Calendar
def get_calendar_service():
    """Get authenticated Google Calendar service"""
    creds = None
    token_path = "token.json"
    
    # Load existing token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, CALENDAR_SCOPES)
    
    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            if not os.path.exists(GOOGLE_CALENDAR_CREDENTIALS):
                raise FileNotFoundError(
                    f"Google Calendar credentials file '{GOOGLE_CALENDAR_CREDENTIALS}' not found. "
                    "Download from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CALENDAR_CREDENTIALS, CALENDAR_SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save credentials for next run
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)

@retry_with_backoff()
def create_calendar_event(title: str, start_time: str, end_time: str, description: str = "") -> str:
    """Create a Google Calendar event
    
    Args:
        title: Event title
        start_time: Start time in ISO format (e.g., "2024-12-25T10:00:00")
        end_time: End time in ISO format
        description: Event description (optional)
    """
    try:
        logger.info(f"Creating calendar event: {title}")
        service = get_calendar_service()
        
        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
            },
        }
        
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        event_link = created_event.get('htmlLink')
        
        logger.info(f"✅ Calendar event created: {title}")
        return f"✅ Calendar event created: {title}\nLink: {event_link}"
        
    except FileNotFoundError as e:
        logger.error(str(e))
        return f"❌ {str(e)}"
    except Exception as e:
        logger.error(f"Error creating calendar event: {e}")
        raise

@retry_with_backoff()
def list_calendar_events(days_ahead: int = 7) -> str:
    """List upcoming calendar events
    
    Args:
        days_ahead: Number of days to look ahead (default: 7)
    """
    try:
        logger.info(f"Listing calendar events for next {days_ahead} days")
        service = get_calendar_service()
        
        now = datetime.utcnow().isoformat() + 'Z'
        end_date = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=end_date,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"📅 No upcoming events in the next {days_ahead} days"
        
        result = f"📅 Upcoming events (next {days_ahead} days):\n\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No title')
            result += f"• {summary} - {start}\n"
        
        logger.info(f"Listed {len(events)} calendar events")
        return result.strip()
        
    except FileNotFoundError as e:
        logger.error(str(e))
        return f"❌ {str(e)}"
    except Exception as e:
        logger.error(f"Error listing calendar events: {e}")
        raise

# Map action -> function
def do_web_search_task(params: dict, memory: dict) -> str:
    """Execute web search task"""
    try:
        query = params.get("query") or params.get("q") or ""
        if not query:
            logger.warning("Web search task missing query parameter")
            return "❌ Missing query"
        
        logger.info(f"🔎 Running search for: {query}")
        print(f"🔎 Running search for: {query}")
        
        results = tavily_search(query)
        formatted = format_search_results(results)
        
        # optionally ask Gemini to summarize the formatted results into a short digest
        if formatted and len(formatted) > 600:
            try:
                summary = summarize_text(formatted, topic_hint=query, max_words=200)
                memory["last_search_summary"] = summary
                memory["last_search_full"] = formatted
                logger.info("Search results summarized successfully")
                return summary
            except Exception as e:
                logger.warning(f"Failed to summarize search results: {e}. Using full results.")
                memory["last_search_summary"] = formatted
                memory["last_search_full"] = formatted
                return formatted
        else:
            memory["last_search_summary"] = formatted
            memory["last_search_full"] = formatted
            return formatted
    except Exception as e:
        logger.error(f"Error in do_web_search_task: {e}")
        return f"❌ Search failed: {str(e)}"

def do_send_email_task(params: dict, memory: dict) -> str:
    """Execute send email task"""
    try:
        to_email = params.get("to_email") or params.get("to") or params.get("email")
        subject = params.get("subject", "No subject")
        body = params.get("body", "")
        
        if not to_email:
            logger.warning("Send email task missing recipient")
            return "❌ Missing recipient email (to_email)"
        
        # Replace common placeholders with actual search summary
        if ("[Insert" in body) or ("{search" in body) or ("[search" in body.lower()):
            # Prefer concise summary, fallback to full results
            replacement = memory.get("last_search_summary") or memory.get("last_search_full") or ""
            body = re.sub(r"\[(?:Insert|Insert Web Search Results Here|search results here)\]", replacement, body, flags=re.IGNORECASE)
            body = body.replace("{search_summary}", replacement)
            logger.debug("Replaced placeholders in email body with search results")
        
        # If body is empty but we have a search summary, use it
        if not body.strip() and memory.get("last_search_summary"):
            body = memory["last_search_summary"]
            logger.debug("Using search summary as email body")
        
        print(f"✉️ Sending email to {to_email} (subject: {subject})...")
        return send_email(to_email, subject, body)
    except Exception as e:
        logger.error(f"Error in do_send_email_task: {e}")
        return f"❌ Email failed: {str(e)}"

def do_weather_task(params: dict, memory: dict) -> str:
    """Execute weather task"""
    try:
        location = params.get("location") or params.get("city")
        units = params.get("units", "metric")
        
        if not location:
            logger.warning("Weather task missing location parameter")
            return "❌ Missing location"
        
        print(f"🌤️ Getting weather for: {location}")
        result = get_weather(location, units)
        memory["last_weather"] = result
        return result
    except Exception as e:
        logger.error(f"Error in do_weather_task: {e}")
        return f"❌ Weather failed: {str(e)}"

def do_slack_task(params: dict, memory: dict) -> str:
    """Execute Slack message task"""
    try:
        channel = params.get("channel")
        message = params.get("message") or params.get("text")
        
        if not channel:
            logger.warning("Slack task missing channel parameter")
            return "❌ Missing channel"
        if not message:
            logger.warning("Slack task missing message parameter")
            return "❌ Missing message"
        
        # Replace placeholders with search results if present
        if ("[Insert" in message) or ("{search" in message):
            replacement = memory.get("last_search_summary") or memory.get("last_search_full") or ""
            message = re.sub(r"\[(?:Insert|Insert Web Search Results Here|search results here)\]", replacement, message, flags=re.IGNORECASE)
            message = message.replace("{search_summary}", replacement)
        
        print(f"💬 Sending Slack message to {channel}...")
        return send_slack_message(channel, message)
    except Exception as e:
        logger.error(f"Error in do_slack_task: {e}")
        return f"❌ Slack failed: {str(e)}"

def do_calendar_create_task(params: dict, memory: dict) -> str:
    """Execute calendar event creation task"""
    try:
        title = params.get("title") or params.get("summary")
        start_time = params.get("start_time") or params.get("start")
        end_time = params.get("end_time") or params.get("end")
        description = params.get("description", "")
        
        if not title:
            logger.warning("Calendar create task missing title")
            return "❌ Missing event title"
        if not start_time:
            logger.warning("Calendar create task missing start_time")
            return "❌ Missing start_time (use ISO format: 2024-12-25T10:00:00)"
        if not end_time:
            logger.warning("Calendar create task missing end_time")
            return "❌ Missing end_time (use ISO format: 2024-12-25T11:00:00)"
        
        print(f"📅 Creating calendar event: {title}")
        return create_calendar_event(title, start_time, end_time, description)
    except Exception as e:
        logger.error(f"Error in do_calendar_create_task: {e}")
        return f"❌ Calendar create failed: {str(e)}"

def do_calendar_list_task(params: dict, memory: dict) -> str:
    """Execute calendar list task"""
    try:
        days_ahead = params.get("days_ahead", 7)
        try:
            days_ahead = int(days_ahead)
        except (ValueError, TypeError):
            days_ahead = 7
        
        print(f"📅 Listing calendar events for next {days_ahead} days...")
        result = list_calendar_events(days_ahead)
        memory["last_calendar_events"] = result
        return result
    except Exception as e:
        logger.error(f"Error in do_calendar_list_task: {e}")
        return f"❌ Calendar list failed: {str(e)}"
    except Exception as e:
        logger.error(f"Error in do_send_email_task: {e}")
        return f"❌ Email failed: {str(e)}"

ACTION_HANDLERS = {
    "web_search": do_web_search_task,
    "search": do_web_search_task,
    "send_email": do_send_email_task,
    "email": do_send_email_task,
    "weather": do_weather_task,
    "get_weather": do_weather_task,
    "slack": do_slack_task,
    "send_slack": do_slack_task,
    "calendar_create": do_calendar_create_task,
    "create_event": do_calendar_create_task,
    "calendar_list": do_calendar_list_task,
    "list_events": do_calendar_list_task,
}

# Gemini -> tasks parsing
def extract_json_from_text(text: str) -> str:
    """Strip markdown fences and extract JSON. Returns JSON string or empty string."""
    try:
        if not text:
            return ""
        txt = text.strip()
        # Remove leading/trailing markdown fences (```json ... ``` or ``` ... ```)
        txt = re.sub(r"^```(?:json)?\s*", "", txt, flags=re.IGNORECASE)
        txt = re.sub(r"\s*```$", "", txt)
        logger.debug("Extracted JSON from markdown fences")
        return txt.strip()
    except Exception as e:
        logger.error(f"Error extracting JSON from text: {e}")
        return ""

@retry_with_backoff()
def generate_tasks(user_input: str) -> TaskList:
    """Generate task list from user input using Gemini"""
    try:
        logger.info(f"Generating tasks for user input: {user_input}")
        prompt = (
            "You are a task planner. Convert the user's request into strict JSON only. "
            "Use these actions with parameter names exactly as shown:\n\n"
            "- web_search(query: string)\n"
            "- send_email(to_email: string, subject: string, body: string)\n"
            "- weather(location: string, units: string = 'metric' or 'imperial')\n"
            "- slack(channel: string, message: string)\n"
            "- calendar_create(title: string, start_time: string, end_time: string, description: string)\n"
            "- calendar_list(days_ahead: int = 7)\n\n"
            "Notes:\n"
            "- For calendar times, use ISO format: '2024-12-25T10:00:00'\n"
            "- For Slack channels, use channel name like '#general' or '@username'\n"
            "- Weather units: 'metric' (Celsius) or 'imperial' (Fahrenheit)\n\n"
            "Return JSON in this exact schema:\n"
            '{ "tasks": [ { "action": "web_search", "query": "..." }, '
            '{ "action": "weather", "location": "...", "units": "metric" } ] }\n\n'
            f'User request: {user_input}\n'
            "Return ONLY the JSON (you may optionally wrap with ```json ... ```)."
        )
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(prompt)
        raw = (resp.text or "").strip()
        print("💬 Gemini raw response:\n", raw)
        logger.debug(f"Gemini response: {raw[:200]}...")

        json_text = extract_json_from_text(raw)
        if not json_text:
            logger.error("No JSON extracted from Gemini response")
            print("❌ No JSON extracted from Gemini response.")
            return TaskList(tasks=[])

        # robust parsing: accept object with tasks or array of task dicts
        try:
            parsed = json.loads(json_text)
            tasks = []
            if isinstance(parsed, dict) and "tasks" in parsed:
                for t in parsed["tasks"]:
                    tasks.append(Task(**t))
            elif isinstance(parsed, list):
                for t in parsed:
                    tasks.append(Task(**t))
            else:
                logger.error(f"Unexpected JSON shape: {type(parsed)}")
                print("❌ Unexpected JSON shape:", type(parsed))
                return TaskList(tasks=[])
            logger.info(f"Successfully generated {len(tasks)} tasks")
            return TaskList(tasks=tasks)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            print("❌ Error parsing JSON from Gemini:", e)
            print("Raw JSON candidate:\n", json_text[:2000])
            return TaskList(tasks=[])
    except Exception as e:
        logger.error(f"Error in generate_tasks: {e}")
        raise

# Orchestration
def execute_task_list(task_list: TaskList):
    """Execute a list of tasks with shared memory context"""
    if not task_list.tasks:
        logger.warning("No tasks to execute")
        print("⚠ No tasks to execute.")
        return
    
    logger.info(f"Starting execution of {len(task_list.tasks)} tasks")
    memory: Dict[str, Any] = {}
    
    for i, task in enumerate(task_list.tasks, start=1):
        action = task.action
        params = task.params
        print(f"\n--- Task {i}/{len(task_list.tasks)}: {action} ---")
        logger.info(f"Executing task {i}/{len(task_list.tasks)}: {action}")
        
        handler = ACTION_HANDLERS.get(action)
        if not handler:
            logger.warning(f"No handler found for action '{action}'")
            print(f"⚠ No handler for action '{action}', skipping.")
            continue
        
        try:
            result = handler(params, memory)
            print("Result:", result)
            logger.info(f"Task {i} completed successfully")
        except Exception as e:
            logger.error(f"Exception running task {i} ({action}): {e}", exc_info=True)
            print(f"❌ Exception running task {action}: {e}")
    
    logger.info("Task execution completed")

# main
if __name__ == "__main__":
    try:
        logger.info("=== Agentic AI Starting ===")
        print("🤖 Agentic AI (Gemini + Tavily + Gmail) Ready")
        user_req = input("What do you want me to do? ").strip()
        
        if not user_req:
            logger.warning("Empty user input received")
            print("⚠ No input provided. Exiting.")
            exit(0)
        
        logger.info(f"User request: {user_req}")
        tasks = generate_tasks(user_req)
        print(f"\n✅ Planned tasks: {tasks}\n")
        execute_task_list(tasks)
        logger.info("=== Agentic AI Completed Successfully ===")
    except KeyboardInterrupt:
        logger.info("User interrupted execution")
        print("\n⚠ Execution interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}")
        exit(1)