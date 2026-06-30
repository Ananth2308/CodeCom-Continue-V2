"""Approval system for dangerous operations.

Provides both chat-inline and API-based approval flows:
1. Chat-inline: Agent pauses and asks in the stream, user responds in next message
2. API-based: External UI polls /v1/sessions and calls /v1/sessions/{id}/approve
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApprovalRequest:
    tool_name: str
    arguments: dict
    tool_call_id: str
    requested_at: float = field(default_factory=time.time)
    response: Optional[str] = None
    resolved: bool = False


class ApprovalManager:
    def __init__(self, timeout: float = 300.0):
        self.timeout = timeout
        self._pending: dict[str, ApprovalRequest] = {}

    def request(self, session_id: str, tool_name: str, arguments: dict, tool_call_id: str) -> ApprovalRequest:
        req = ApprovalRequest(
            tool_name=tool_name,
            arguments=arguments,
            tool_call_id=tool_call_id,
        )
        self._pending[session_id] = req
        return req

    def respond(self, session_id: str, response: str) -> bool:
        req = self._pending.get(session_id)
        if not req or req.resolved:
            return False
        req.response = response
        req.resolved = True
        return True

    def get_pending(self, session_id: str) -> Optional[ApprovalRequest]:
        req = self._pending.get(session_id)
        if req and not req.resolved:
            return req
        return None

    async def wait_for_response(self, session_id: str) -> str:
        """Wait for the approval response or timeout."""
        req = self._pending.get(session_id)
        if not req:
            return "deny"

        start = time.time()
        while not req.resolved:
            if time.time() - start > self.timeout:
                req.response = "timeout"
                req.resolved = True
                break
            await asyncio.sleep(0.1)

        response = req.response or "deny"
        del self._pending[session_id]
        return response

    def list_pending(self) -> list[dict]:
        return [
            {
                "session_id": sid,
                "tool": req.tool_name,
                "arguments": req.arguments,
                "requested_at": req.requested_at,
            }
            for sid, req in self._pending.items()
            if not req.resolved
        ]


approval_manager = ApprovalManager()
