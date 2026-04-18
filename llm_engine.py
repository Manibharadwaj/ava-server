"""AVA LLM Engine - Ollama"""
import requests
from config import OLLAMA_MODEL, OLLAMA_URL

def _load_system_prompt() -> str:
    try:
        with open("prompts/system_prompt.txt") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "You are AVA, a friendly sales agent. Keep responses short."

SYSTEM_PROMPT = _load_system_prompt()

class LlmEngine:
    def generate_reply(self, user_message: str, history: list = None, lead_name: str = "") -> tuple[str, str]:
        if history is None:
            history = []
        if len(history) > 20:
            history = history[-20:]

        system_content = SYSTEM_PROMPT
        if lead_name:
            system_content += f"\nYou are currently calling {lead_name}. Address them by name if natural."

        messages = [{"role": "system", "content": system_content}] + history + [{"role": "user", "content": user_message}]
        ai_reply = self._chat(messages)
        intent = self._detect_intent(ai_reply, user_message)
        return ai_reply, intent

    def _chat(self, messages: list) -> str:
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": OLLAMA_MODEL, "messages": messages, "stream": False,
                "options": {"temperature": 0.7, "num_predict": 100}
            }, timeout=30)
            r.raise_for_status()
            reply = r.json()["message"]["content"].strip()
            print(f"[LLM] Says: {reply}")
            return reply
        except Exception as e:
            print(f"[LLM] Error: {e}")
            return "I'm sorry, could you repeat that?"

    def _detect_intent(self, ai_response: str, user_text: str) -> str:
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate", json={
                "model": OLLAMA_MODEL, "stream": False,
                "prompt": f"""Classify caller intent as ONE of: "interested", "not_interested", "talking", "ended"
Caller said: "{user_text}"
AI replied: "{ai_response}"
Intent:""",
                "options": {"num_predict": 5}
            }, timeout=10)
            t = r.json()["response"].strip().lower()
            if "interest" in t and "not" not in t: return "interested"
            if "not" in t: return "not_interested"
            if "end" in t: return "ended"
            return "talking"
        except:
            return "talking"

_engine = None
def get_llm_engine() -> LlmEngine:
    global _engine
    if _engine is None:
        _engine = LlmEngine()
    return _engine