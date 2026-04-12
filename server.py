"""AVA Server - FastAPI WebSocket"""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import db_manager
from stt_engine import get_stt_engine
from llm_engine import get_llm_engine
from config import WS_HOST, WS_PORT, HEARTBEAT_INTERVAL, HEARTBEAT_TIMEOUT, CALL_MAX_DURATION, SAMPLE_RATE

class PhoneConnection:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.call_id = None
        self.audio_buffer = bytearray()
        self.conversation_history = []
        self.last_heartbeat = time.time()
        self.call_start_time = None
    def reset_call(self):
        self.audio_buffer = bytearray()
        self.conversation_history = []
        self.call_start_time = None

phones: dict[int, PhoneConnection] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[AVA] Server starting...")
    db_manager.init_db()
    get_stt_engine()  # pre-warm
    yield
    print("[AVA] Server shutting down")

app = FastAPI(title="AVA Server", lifespan=lifespan)

@app.get("/")
async def health():
    return {"status": "running", "connected_phones": len(phones), "stats": db_manager.get_stats()}

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
    except: return
    t = msg.get("type", "")
    if t == "register":
        await conn.ws.send_json({"type": "register_ack", "timestamp": int(time.time()*1000)})
    elif t == "silence_detected":
        await process_audio(conn)
    elif t == "call_state":
        state = msg.get("state", "")
        phone = msg.get("phone", "")
        if state == "active":
            conn.call_start_time = time.time()
            db_manager.update_lead_status(phone, "calling")
    elif t == "next_lead":
        lead = db_manager.get_next_lead()
        if lead:
            await conn.ws.send_json({"type": "next_lead_info", "payload": lead})
        else:
            await conn.ws.send_json({"type": "error", "payload": {"code": "no_leads", "message": "No pending leads"}})
    elif t == "lead_status":
        db_manager.update_lead_status(msg.get("phone",""), msg.get("status",""), msg.get("notes",""))
    elif t == "heartbeat":
        conn.last_heartbeat = time.time()
        await conn.ws.send_json({"type": "heartbeat_ack"})

async def handle_binary(conn: PhoneConnection, data: bytes):
    # Format: [4 bytes header len][JSON header][PCM bytes]
    if len(data) < 4: return
    import struct
    hlen = struct.unpack(">I", data[:4])[0]
    if len(data) < 4 + hlen: return
    header = json.loads(data[4:4+hlen].decode())
    pcm = data[4+hlen:]
    conn.audio_buffer.extend(pcm)
    # Check max duration
    if conn.call_start_time and time.time() - conn.call_start_time > CALL_MAX_DURATION:
        await conn.ws.send_json({"type": "hangup", "payload": {"reason": "max_duration"}})

async def process_audio(conn: PhoneConnection):
    if not conn.audio_buffer: return
    stt = get_stt_engine()
    llm = get_llm_engine()
    loop = asyncio.get_event_loop()
    user_text = await loop.run_in_executor(None, stt.transcribe_pcm, bytes(conn.audio_buffer))
    conn.audio_buffer.clear()
    if not user_text or user_text.lower().strip() in ("", "uh", "um", "hello?", "hmm"):
        user_text = "Hello?"
    await conn.ws.send_json({"type": "transcription", "payload": {"text": user_text, "is_final": True, "confidence": 0.9}})
    ai_reply, intent = await loop.run_in_executor(None, llm.generate_reply, user_text, conn.conversation_history)
    await conn.ws.send_json({"type": "ai_reply", "payload": {"text": ai_reply, "intent": intent}, "call_id": conn.call_id})
    conn.conversation_history.append({"role": "user", "content": user_text})
    conn.conversation_history.append({"role": "assistant", "content": ai_reply})
    print(f"[AVA] Intent: {intent} | Reply: {ai_reply[:50]}...")

if __name__ == "__main__":
    uvicorn.run("server:app", host=WS_HOST, port=WS_PORT, log_level="info",
                ws_ping_interval=HEARTBEAT_INTERVAL, ws_ping_timeout=HEARTBEAT_TIMEOUT)