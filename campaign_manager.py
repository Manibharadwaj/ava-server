"""AVA Campaign Manager - Auto-dialer orchestration"""
import asyncio
import time
import uuid
import db_manager
from config import CAMPAIGN_DELAY, CAMPAIGN_MAX_RETRIES

class CampaignManager:
    def __init__(self):
        self.state = "idle"  # idle, running, paused
        self.current_lead = None
        self.current_call_id = None
        self.stats = {"calls_made": 0, "interested": 0, "not_interested": 0, "no_answer": 0, "error": 0}
        self._phone_conn = None  # reference to the active phone WebSocket connection

    def start(self, phone_conn):
        self._phone_conn = phone_conn
        self.state = "running"
        asyncio.create_task(self._run_campaign())

    def stop(self):
        self.state = "idle"
        self.current_lead = None

    def pause(self):
        self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "running"
            asyncio.create_task(self._run_campaign())

    def on_call_ended(self, reason: str):
        if self.current_lead:
            status = {
                "interested": "interested",
                "not_interested": "not_interested",
            }.get(reason, "no_answer")

            db_manager.update_lead_status(self.current_lead["phone"], status, notes=f"Intent: {reason}")
            self.stats["calls_made"] += 1
            if status == "interested":
                self.stats["interested"] += 1
            elif status == "not_interested":
                self.stats["not_interested"] += 1
            else:
                self.stats["no_answer"] += 1

            if self.current_call_id:
                db_manager.end_call_log(self.current_call_id, reason)

        self.current_lead = None
        self.current_call_id = None

    async def _run_campaign(self):
        while self.state == "running":
            lead = db_manager.get_next_lead()
            if not lead:
                print("[Campaign] No more pending leads")
                self.state = "idle"
                break

            self.current_lead = lead
            self.current_call_id = str(uuid.uuid4())

            # Log the call start
            db_manager.add_call_log(lead["id"], self.current_call_id)

            # Send next lead to phone app
            if self._phone_conn:
                await self._phone_conn.ws.send_json({
                    "type": "next_lead_info",
                    "payload": lead,
                    "call_id": self.current_call_id,
                })
                print(f"[Campaign] Calling {lead['name'] or lead['phone']}")

            # Wait for call to complete (phone app will send lead_status)
            # Then wait the configured delay before next call
            await asyncio.sleep(CAMPAIGN_DELAY)

    def get_status(self):
        return {
            "state": self.state,
            "current_lead": self.current_lead,
            "stats": self.stats,
            "pending_count": len(db_manager.get_pending_leads()),
        }

_campaign = None
def get_campaign_manager() -> CampaignManager:
    global _campaign
    if _campaign is None:
        _campaign = CampaignManager()
    return _campaign