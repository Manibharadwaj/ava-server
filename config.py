# AVA Server Configuration
import os
from dotenv import load_dotenv

load_dotenv()

WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", "8765"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "en")
TTS_VOICE = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", "10"))
CALL_MAX_DURATION = int(os.getenv("CALL_MAX_DURATION", "180"))
DB_FILE = os.getenv("DB_FILE", "leads.db")
CAMPAIGN_DELAY = int(os.getenv("CAMPAIGN_DELAY", "30"))
CAMPAIGN_MAX_RETRIES = int(os.getenv("CAMPAIGN_MAX_RETRIES", "3"))