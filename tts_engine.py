"""AVA TTS Engine - Edge-TTS
Server-side TTS for generating audio when phone TTS doesn't reach the call uplink.
"""
import asyncio
import os
import subprocess
from typing import Optional
from config import TTS_VOICE, SAMPLE_RATE


class TtsEngine:

    async def _generate_speech_mp3(self, text: str, output_mp3: str):
        """Generate speech using Edge-TTS (saves as MP3)."""
        import edge_tts
        communicate = edge_tts.Communicate(text, TTS_VOICE)
        await communicate.save(output_mp3)

    def synthesize_to_file(self, text: str, output_wav: str) -> Optional[str]:
        """Convert text to WAV file (16kHz, mono)."""
        mp3_file = output_wav.replace(".wav", ".mp3")
        try:
            asyncio.run(self._generate_speech_mp3(text, mp3_file))
        except Exception as e:
            print(f"[TTS] Edge-TTS error: {e}")
            return None

        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", mp3_file,
                "-ar", str(SAMPLE_RATE), "-ac", "1", output_wav
            ], capture_output=True, timeout=10)
            os.remove(mp3_file)
            print(f"[TTS] Saved to {output_wav}")
            return output_wav
        except Exception as e:
            print(f"[TTS] FFmpeg error: {e}")
            return None

    def synthesize_to_pcm(self, text: str) -> Optional[bytes]:
        """Convert text to raw PCM bytes (16-bit LE, mono, 16kHz).
        Useful for sending audio directly to phone via WebSocket.
        """
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        result = self.synthesize_to_file(text, wav_path)
        if result is None:
            return None

        try:
            with open(wav_path, "rb") as f:
                f.seek(44)  # Skip WAV header
                pcm_data = f.read()
            os.remove(wav_path)
            print(f"[TTS] PCM size: {len(pcm_data)} bytes")
            return pcm_data
        except Exception as e:
            print(f"[TTS] PCM extraction error: {e}")
            if os.path.exists(wav_path):
                os.remove(wav_path)
            return None


_engine = None
def get_tts_engine() -> TtsEngine:
    global _engine
    if _engine is None:
        _engine = TtsEngine()
    return _engine