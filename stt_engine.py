"""AVA STT Engine - Whisper"""
import numpy as np
import whisper
from config import WHISPER_MODEL, STT_LANGUAGE, SAMPLE_RATE

class SttEngine:
    def __init__(self):
        self.model = None

    def _load(self):
        if self.model is None:
            print(f"[STT] Loading Whisper {WHISPER_MODEL}...")
            self.model = whisper.load_model(WHISPER_MODEL)
        return self.model

    def transcribe_pcm(self, pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        model = self._load()
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000:
            duration = len(audio_np) / sample_rate
            target_len = int(duration * 16000)
            indices = np.linspace(0, len(audio_np) - 1, target_len)
            audio_np = np.interp(indices, np.arange(len(audio_np)), audio_np)
        try:
            result = model.transcribe(audio_np, language=STT_LANGUAGE, fp16=False, condition_on_previous_text=False)
            text = result["text"].strip()
            print(f"[STT] Heard: {text}")
            return text
        except Exception as e:
            print(f"[STT] Error: {e}")
            return ""

_engine = None
def get_stt_engine() -> SttEngine:
    global _engine
    if _engine is None:
        _engine = SttEngine()
    return _engine