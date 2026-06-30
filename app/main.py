import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.agent_loop import AgentLoop
from app.core.file_watcher import file_watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    await file_watcher.start()
    yield
    await file_watcher.stop()


app = FastAPI(title="Dev Agent Proxy", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Stores suspended agent state waiting for approval
# Key: conversation fingerprint, Value: suspended state dict
suspended_sessions: dict[str, dict] = {}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "agent"
    messages: list[ChatMessage]
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None


# --- OpenAI-Compatible Endpoints ---


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint."""

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Check if this is a response to a suspended session
    conv_key = _conversation_key(messages)
    suspended = suspended_sessions.pop(conv_key, None)

    if suspended:
        # User is responding to an approval request — resume the agent loop
        user_response = messages[-1]["content"].strip().lower()
        approved = user_response not in ("no", "deny", "reject", "cancel", "n")

        if request.stream:
            return StreamingResponse(
                _stream_resumed_agent(suspended, approved, messages),
                media_type="text/event-stream",
            )
        else:
            full_response = ""
            async for chunk in _run_resumed_agent(suspended, approved, messages):
                full_response += chunk
            return _non_stream_response(full_response)

    # New conversation turn — run agent
    # Inject file watcher context if there are recent changes
    change_summary = file_watcher.get_change_summary()
    if change_summary:
        context_msg = {
            "role": "system",
            "content": f"[File Watcher] {change_summary}",
        }
        messages.insert(1, context_msg)

    if request.stream:
        return StreamingResponse(
            _stream_agent_response(messages),
            media_type="text/event-stream",
        )
    else:
        full_response = ""
        async for chunk in _run_agent(messages):
            full_response += chunk
        return _non_stream_response(full_response)


async def _run_agent(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Run the agent loop, handling approval by suspending."""
    agent = AgentLoop()
    try:
        async for event in agent.run(messages):
            if isinstance(event, dict) and event.get("type") == "approval_needed":
                # Suspend: save state and stop streaming
                conv_key = _conversation_key(messages)
                suspended_sessions[conv_key] = {
                    "messages_so_far": event["messages_so_far"],
                    "tool_call": event["tool_call"],
                    "original_messages": messages,
                }
                # Tell user what needs approval and end the stream
                tool_name = event["tool_call"]["function"]["name"]
                arguments = json.loads(event["tool_call"]["function"]["arguments"])
                msg = f"\n**Approval required** for `{tool_name}`:\n"
                msg += f"```json\n{json.dumps(arguments, indent=2)}\n```\n"
                msg += "\nReply **yes** to approve or **no** to deny."
                yield msg
                return
            else:
                yield event
    finally:
        await agent.close()


async def _run_resumed_agent(
    suspended: dict, approved: bool, messages: list[dict]
) -> AsyncGenerator[str, None]:
    """Resume an agent after approval."""
    agent = AgentLoop()
    try:
        if approved:
            yield "Approved. Executing...\n\n"
        else:
            yield "Denied.\n\n"

        async for event in agent.resume(
            suspended["messages_so_far"],
            suspended["tool_call"],
            approved,
        ):
            if isinstance(event, dict) and event.get("type") == "approval_needed":
                # Another approval needed — suspend again
                conv_key = _conversation_key(messages)
                suspended_sessions[conv_key] = {
                    "messages_so_far": event["messages_so_far"],
                    "tool_call": event["tool_call"],
                    "original_messages": messages,
                }
                tool_name = event["tool_call"]["function"]["name"]
                arguments = json.loads(event["tool_call"]["function"]["arguments"])
                msg = f"\n**Approval required** for `{tool_name}`:\n"
                msg += f"```json\n{json.dumps(arguments, indent=2)}\n```\n"
                msg += "\nReply **yes** to approve or **no** to deny."
                yield msg
                return
            else:
                yield event
    finally:
        await agent.close()


async def _stream_agent_response(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream SSE events in OpenAI format."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())

    async for chunk in _run_agent(messages):
        data = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "dev-agent",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": chunk},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(data)}\n\n"

    final = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "dev-agent",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_resumed_agent(
    suspended: dict, approved: bool, messages: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream SSE events for resumed agent."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())

    async for chunk in _run_resumed_agent(suspended, approved, messages):
        data = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "dev-agent",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": chunk},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(data)}\n\n"

    final = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "dev-agent",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


def _non_stream_response(content: str) -> JSONResponse:
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "dev-agent",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


def _conversation_key(messages: list[dict]) -> str:
    """Generate a stable key from the conversation's first user message.
    Continue sends the full conversation history each turn, so the first
    user message stays constant across the approval exchange."""
    for msg in messages:
        if msg["role"] == "user":
            return str(hash(msg["content"]))
    return "default"


# --- Health & Info Endpoints ---


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "dev-agent",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "dev-agent-proxy",
            }
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "workspace": settings.workspace_dir}


@app.get("/v1/pending")
async def list_pending():
    """List pending approval requests."""
    return {
        "pending": [
            {
                "conv_key": key,
                "tool": state["tool_call"]["function"]["name"],
                "arguments": json.loads(state["tool_call"]["function"]["arguments"]),
            }
            for key, state in suspended_sessions.items()
        ]
    }
