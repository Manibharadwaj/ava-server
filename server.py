"""AVA Server - FastAPI WebSocket + REST API"""
import asyncio
import json
import struct
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import db_manager
from stt_engine import get_stt_engine
from llm_engine import get_llm_engine
from tts_engine import get_tts_engine
from campaign_manager import get_campaign_manager
from config import WS_HOST, WS_PORT, HEARTBEAT_INTERVAL, HEARTBEAT_TIMEOUT, CALL_MAX_DURATION, SAMPLE_RATE

class PhoneConnection:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.call_id = None
        self.audio_buffer = bytearray()
        self.conversation_history = []
        self.last_heartbeat = time.time()
        self.call_start_time = None
        self.current_lead = None
        self.last_audio_time = None  # for VAD
        self.has_speech = False       # has detected speech in current buffer
        self.vad_task = None          # asyncio task for VAD processing

    def reset_call(self):
        self.audio_buffer = bytearray()
        self.conversation_history = []
        self.call_start_time = None
        self.current_lead = None
        self.last_audio_time = None
        self.has_speech = False

phones: dict[int, PhoneConnection] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[AVA] Server starting...")
    db_manager.init_db()
    get_stt_engine()  # pre-warm
    yield
    print("[AVA] Server shutting down")

app = FastAPI(title="AVA Server", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Health ──────────────────────────────────

@app.get("/")
async def health():
    campaign = get_campaign_manager()
    return {
        "status": "running",
        "connected_phones": len(phones),
        "stats": db_manager.get_stats(),
        "campaign": campaign.get_status(),
    }

# ─── REST API: Leads ────────────────────────

class LeadInput(BaseModel):
    phone: str
    name: str = ""

class LeadBulkInput(BaseModel):
    leads: list[LeadInput]

@app.post("/api/leads")
async def add_leads(data: LeadBulkInput):
    count = db_manager.add_leads_bulk([l.model_dump() for l in data.leads])
    return {"added": count}

@app.post("/api/leads/csv")
async def add_leads_csv(file: bytes = None):
    # Accept CSV file content
    import tempfile, csv, io
    content = file or b""
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    leads = []
    for row in reader:
        phone = row.get("phone", "").strip()
        name = row.get("name", "").strip()
        if phone:
            leads.append({"phone": phone, "name": name})
    count = db_manager.add_leads_bulk(leads)
    return {"added": count}

@app.get("/api/leads")
async def list_leads(limit: int = 100, offset: int = 0):
    leads, total = db_manager.get_all_leads(limit, offset)
    return {"leads": leads, "total": total}

@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int):
    db_manager.delete_lead(lead_id)
    return {"deleted": True}

@app.get("/api/stats")
async def get_stats():
    return db_manager.get_stats()

# ─── REST API: Call History ──────────────────

@app.get("/api/call-logs")
async def list_call_logs(limit: int = 50, offset: int = 0):
    return {"logs": db_manager.get_call_logs(limit, offset)}

# ─── REST API: Campaign ─────────────────────

@app.post("/api/campaign/start")
async def start_campaign():
    campaign = get_campaign_manager()
    if not phones:
        return {"error": "No phone connected"}
    conn = list(phones.values())[0]
    campaign.start(conn)
    return {"status": "started"}

@app.post("/api/campaign/stop")
async def stop_campaign():
    campaign = get_campaign_manager()
    campaign.stop()
    return {"status": "stopped"}

@app.post("/api/campaign/pause")
async def pause_campaign():
    campaign = get_campaign_manager()
    campaign.pause()
    return {"status": "paused"}

@app.post("/api/campaign/resume")
async def resume_campaign():
    campaign = get_campaign_manager()
    campaign.resume()
    return {"status": "resumed"}

@app.get("/api/campaign/status")
async def campaign_status():
    campaign = get_campaign_manager()
    return campaign.get_status()

# ─── WebSocket ───────────────────────────────

@app.websocket("/ava")
async def ava_endpoint(websocket: WebSocket):
    await websocket.accept()
    pid = id(websocket)
    conn = PhoneConnection(websocket)
    phones[pid] = conn
    print(f"[WS] Phone connected: {pid}")
    try:
        while True:
            msg = await websocket.receive()
            if "text" in msg:
                await handle_text(conn, msg["text"])
            elif "bytes" in msg:
                await handle_binary(conn, msg["bytes"])
    except WebSocketDisconnect:
        print(f"[WS] Phone disconnected: {pid}")
    except Exception as e:
        print(f"[WS] Error: {e}")
    finally:
        phones.pop(pid, None)

async def handle_text(conn: PhoneConnection, text: str):
    try:
        msg = json.loads(text)
    except:
        return
    t = msg.get("type", "")

    if t == "register":
        await conn.ws.send_json({"type": "register_ack", "timestamp": int(time.time() * 1000)})

    elif t == "caller_audio":
        # Phone is streaming caller audio chunks — trigger processing when we have enough
        # For now, accumulate and let silence_detected trigger processing
        pass

    elif t == "silence_detected":
        await process_audio(conn)

    elif t == "call_state":
        state = msg.get("state", "")
        phone = msg.get("phone", "")
        if state == "active":
            conn.call_start_time = time.time()
            conn.call_id = str(uuid.uuid4())
            lead = db_manager.get_lead_by_phone(phone)
            conn.current_lead = lead
            if lead:
                db_manager.add_call_log(lead["id"], conn.call_id)
            db_manager.update_lead_status(phone, "calling")
            # AVA greets first!
            asyncio.create_task(_send_greeting(conn))

    elif t == "next_lead":
        lead = db_manager.get_next_lead()
        if lead:
            await conn.ws.send_json({"type": "next_lead_info", "payload": lead})
        else:
            await conn.ws.send_json({"type": "error", "payload": {"code": "no_leads", "message": "No pending leads"}})

    elif t == "lead_status":
        phone = msg.get("phone", "")
        status = msg.get("status", "")
        notes = msg.get("notes", "")
        db_manager.update_lead_status(phone, status, notes)
        # Notify campaign manager
        campaign = get_campaign_manager()
        campaign.on_call_ended(status)

    elif t == "heartbeat":
        conn.last_heartbeat = time.time()
        await conn.ws.send_json({"type": "heartbeat_ack"})

async def handle_binary(conn: PhoneConnection, data: bytes):
    # Format: [4 bytes header len][JSON header][PCM bytes]
    if len(data) < 4:
        return
    hlen = struct.unpack(">I", data[:4])[0]
    if len(data) < 4 + hlen:
        return
    pcm = data[4 + hlen:]
    conn.audio_buffer.extend(pcm)

    # Simple energy-based VAD: check if this chunk has speech
    if _has_speech(pcm):
        conn.has_speech = True
        conn.last_audio_time = time.time()
        # Cancel any pending VAD timer — caller is still speaking
        if conn.vad_task and not conn.vad_task.done():
            conn.vad_task.cancel()
        # Start a new silence watchdog: if no speech for 1.5s after this, process
        conn.vad_task = asyncio.create_task(_silence_watchdog(conn))

    # Check max duration
    if conn.call_start_time and time.time() - conn.call_start_time > CALL_MAX_DURATION:
        await conn.ws.send_json({"type": "hangup", "payload": {"reason": "max_duration"}})

async def _silence_watchdog(conn: PhoneConnection, silence_timeout: float = 1.5):
    """Wait for silence after speech, then process the audio buffer."""
    try:
        await asyncio.sleep(silence_timeout)
        if conn.has_speech and conn.audio_buffer:
            conn.has_speech = False
            await process_audio(conn)
    except asyncio.CancelledError:
        pass  # Caller is still speaking, cancelled by new speech

async def _send_greeting(conn: PhoneConnection):
    """Generate and send an opening greeting when the call connects."""
    llm = get_llm_engine()
    tts = get_tts_engine()
    loop = asyncio.get_event_loop()

    lead_name = conn.current_lead.get("name", "") if conn.current_lead else ""
    greeting, _ = await loop.run_in_executor(
        None, llm.generate_reply, "The call just connected. Say your opening greeting.", [], lead_name
    )

    # Send text to phone for transcript
    await conn.ws.send_json({
        "type": "ai_reply",
        "payload": {"text": greeting, "intent": "talking"},
        "call_id": conn.call_id,
    })

    # Send audio to phone
    pcm_audio = await loop.run_in_executor(None, tts.synthesize_to_pcm, greeting)
    if pcm_audio:
        header = json.dumps({"type": "ai_reply_audio"}).encode()
        header_bytes = struct.pack(">I", len(header)) + header
        await conn.ws.send_bytes(header_bytes + pcm_audio)

    conn.conversation_history.append({"role": "assistant", "content": greeting})
    print(f"[AVA] Greeting: {greeting[:80]}...")

def _has_speech(pcm_bytes: bytes, threshold: float = 0.02) -> bool:
    """Simple energy-based VAD: returns True if PCM audio has speech-level energy."""
    import numpy as np
    if len(pcm_bytes) < 2:
        return False
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    rms = np.sqrt(np.mean(samples ** 2))
    return rms > threshold

async def process_audio(conn: PhoneConnection):
    if not conn.audio_buffer:
        return

    stt = get_stt_engine()
    llm = get_llm_engine()
    loop = asyncio.get_event_loop()

    # STT: transcribe caller audio
    user_text = await loop.run_in_executor(None, stt.transcribe_pcm, bytes(conn.audio_buffer))
    conn.audio_buffer.clear()

    if not user_text or user_text.lower().strip() in ("", "uh", "um", "hello?", "hmm"):
        user_text = "Hello?"

    # Send transcription to phone
    await conn.ws.send_json({
        "type": "transcription",
        "payload": {"text": user_text, "is_final": True, "confidence": 0.9},
    })

    # LLM: generate reply with lead context
    lead_name = conn.current_lead.get("name", "") if conn.current_lead else ""
    ai_reply, intent = await loop.run_in_executor(
        None, llm.generate_reply, user_text, conn.conversation_history, lead_name
    )

    # Send text reply to phone (for transcript display)
    await conn.ws.send_json({
        "type": "ai_reply",
        "payload": {"text": ai_reply, "intent": intent},
        "call_id": conn.call_id,
    })

    # TTS: generate audio and stream back to phone
    tts = get_tts_engine()
    pcm_audio = await loop.run_in_executor(None, tts.synthesize_to_pcm, ai_reply)
    if pcm_audio:
        header = json.dumps({"type": "ai_reply_audio"}).encode()
        header_bytes = struct.pack(">I", len(header)) + header
        await conn.ws.send_bytes(header_bytes + pcm_audio)

    # Update conversation history
    conn.conversation_history.append({"role": "user", "content": user_text})
    conn.conversation_history.append({"role": "assistant", "content": ai_reply})

    # Save transcript to call log
    if conn.call_id:
        transcript_parts = [f"Caller: {user_text}", f"AVA: {ai_reply}"]
        db_manager.end_call_log(conn.call_id, "in_progress", "\n".join(conn.conversation_history[i]["content"] for i in range(len(conn.conversation_history))))

    print(f"[AVA] Intent: {intent} | Reply: {ai_reply[:50]}...")

if __name__ == "__main__":
    uvicorn.run("server:app", host=WS_HOST, port=WS_PORT, log_level="info",
                ws_ping_interval=HEARTBEAT_INTERVAL, ws_ping_timeout=HEARTBEAT_TIMEOUT)