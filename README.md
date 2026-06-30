# CodeCom Continue V2 — Dev Agent Proxy

An OpenAI-compatible API proxy that transforms any vLLM-hosted model into a fully autonomous coding agent with tool use, human approval workflows, file watching, and self-validation loops. Designed to integrate seamlessly with the [Continue](https://continue.dev/) IDE extension in VS Code.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Directory Structure](#directory-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Local Development (Windows)](#local-development-windows)
  - [Local Development (Linux/macOS)](#local-development-linuxmacos)
  - [EC2 Production Deployment](#ec2-production-deployment)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Dangerous Tools & Approval](#dangerous-tools--approval)
  - [File Watcher](#file-watcher)
  - [Validation Loops](#validation-loops)
- [Running the Project](#running-the-project)
- [API Reference](#api-reference)
  - [POST /v1/chat/completions](#post-v1chatcompletions)
  - [GET /v1/models](#get-v1models)
  - [GET /v1/pending](#get-v1pending)
  - [GET /health](#get-health)
- [Continue IDE Integration](#continue-ide-integration)
- [How the Agent Works](#how-the-agent-works)
  - [Agent Loop](#agent-loop)
  - [Tool Calling Modes](#tool-calling-modes)
  - [Available Tools](#available-tools)
  - [Approval Workflow](#approval-workflow)
  - [Validation Loops](#validation-loops-1)
- [vLLM Backend Setup](#vllm-backend-setup)
- [Development Guide](#development-guide)
  - [Adding a New Tool](#adding-a-new-tool)
  - [Modifying the Agent Prompt](#modifying-the-agent-prompt)
  - [Testing Changes](#testing-changes)
- [Troubleshooting](#troubleshooting)
- [Git & Contributing](#git--contributing)
- [License](#license)

---

## Overview

**Dev Agent Proxy** sits between a client (like the Continue VS Code extension) and a vLLM inference server. It exposes an OpenAI-compatible `/v1/chat/completions` endpoint, but behind the scenes:

1. Receives user messages from Continue (or any OpenAI-compatible client)
2. Injects recent file changes as context (via file watcher)
3. Runs an autonomous agent loop: sends messages to vLLM, parses tool calls, executes tools (file ops, shell commands, grep/glob search), and loops until the task is complete
4. Supports a human-in-the-loop approval workflow for dangerous operations (shell execution, file writes/edits/deletes)
5. Optionally runs internal validation loops (sandbox testing, planning review) before returning the final result to the user

This allows any model served via vLLM (including Qwen, Llama, DeepSeek, etc.) to function as a full coding agent — even models without native function calling support.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Continue IDE Extension                         │
│                  (VS Code / JetBrains / Any Client)                   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP (OpenAI-compatible)
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Dev Agent Proxy                               │
│                       (FastAPI + Uvicorn)                             │
│                                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐  │
│  │ File Watcher │  │  Agent Loop  │  │   Validation Loops         │  │
│  │ (watchfiles) │  │  (core)      │  │ (sandbox test + review)    │  │
│  └──────┬──────┘  └──────┬───────┘  └────────────┬───────────────┘  │
│         │                 │                       │                   │
│         │  ┌──────────────┴──────────────┐       │                   │
│         │  │        Tool Dispatcher       │       │                   │
│         │  ├──────────────────────────────┤       │                   │
│         │  │ file_read   │ file_write     │       │                   │
│         │  │ file_edit   │ file_delete    │       │                   │
│         │  │ glob_search │ grep_search    │       │                   │
│         │  │ shell_exec  │ run_tests      │       │                   │
│         │  │ list_dir    │ request_approval│      │                   │
│         │  └──────────────────────────────┘       │                   │
│         │                                         │                   │
│         └──── Injects change context ─────────────┘                   │
│                                                                      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP (OpenAI API)
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     vLLM Inference Server                             │
│              (Qwen, Llama, DeepSeek, Mistral, etc.)                  │
│                   Running on GPU (EC2/Local)                          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
dev-agent-proxy/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, SSE streaming, endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   ├── agent_loop.py          # Main agent loop (LLM ↔ tools)
│   │   ├── config.py              # Pydantic settings (env-based)
│   │   ├── tool_schemas.py        # OpenAI-format tool definitions
│   │   ├── tool_parser.py         # Fallback parser for non-native tool calling
│   │   ├── file_watcher.py        # Real-time workspace file tracker
│   │   ├── approval.py            # Approval request manager
│   │   └── validation_loops.py    # Sandbox testing & planning review
│   └── tools/
│       ├── __init__.py
│       ├── dispatcher.py          # Routes tool name → implementation
│       ├── filesystem.py          # File ops: read, write, edit, delete, glob, grep, list
│       └── shell.py               # Shell execution & test runner
├── deploy/
│   ├── dev-agent-proxy.service    # Systemd service file
│   └── continue-config-example.json  # Example Continue IDE config
├── run.py                         # Entry point (uvicorn launcher)
├── setup.sh                       # EC2 setup script
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment variable template
├── .env                           # Active config (DO NOT COMMIT)
└── .gitignore                     # Git exclusions
```

---

## Prerequisites

| Requirement | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime (uses `match/case`, `X \| None` type syntax) |
| pip | Latest | Package management |
| vLLM server | Any compatible | LLM inference backend |
| GPU instance (for vLLM) | NVIDIA recommended | Model serving |
| VS Code + Continue extension | Latest | Client IDE (optional, any OpenAI-compatible client works) |

**Python 3.11+ is required** due to use of:
- `match/case` statements (Python 3.10+)
- `X | None` union type syntax (Python 3.10+)
- `asyncio.TaskGroup` patterns

---

## Installation

### Local Development (Windows)

```powershell
# Clone the repository
git clone https://github.com/Ananth2308/CodeCom-Continue-V2.git
cd CodeCom-Continue-V2

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create configuration
copy .env.example .env
# Edit .env with your settings (see Configuration section below)

# Run the development server (with hot reload)
python run.py
```

### Local Development (Linux/macOS)

```bash
# Clone the repository
git clone https://github.com/Ananth2308/CodeCom-Continue-V2.git
cd CodeCom-Continue-V2

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create configuration
cp .env.example .env
# Edit .env with your settings (see Configuration section below)
nano .env

# Run the development server (with hot reload)
python run.py
```

### EC2 Production Deployment

```bash
# SSH into your EC2 instance
ssh ubuntu@your-ec2-ip

# Clone and enter the project
git clone https://github.com/Ananth2308/CodeCom-Continue-V2.git
cd CodeCom-Continue-V2

# Run the automated setup
chmod +x setup.sh
./setup.sh

# Edit configuration
nano .env

# --- Option A: Run directly ---
source .venv/bin/activate
python run.py

# --- Option B: Install as systemd service (recommended for production) ---
sudo cp deploy/dev-agent-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dev-agent-proxy
sudo systemctl start dev-agent-proxy

# Check status
sudo systemctl status dev-agent-proxy

# View logs
sudo journalctl -u dev-agent-proxy -f
```

**Important**: The systemd service file assumes the project is at `/home/ubuntu/dev-agent-proxy`. If you cloned to a different location, edit the service file:

```bash
sudo nano /etc/systemd/system/dev-agent-proxy.service
# Update WorkingDirectory, EnvironmentFile, and ExecStart paths
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root (copy from `.env.example`). All variables use the `AGENT_` prefix.

| Variable | Required | Default | Description |
|---|---|---|---|
| `AGENT_VLLM_BASE_URL` | Yes | `http://localhost:8000/v1` | Full URL to your vLLM server's OpenAI-compatible endpoint |
| `AGENT_VLLM_API_KEY` | Yes | `EMPTY` | Bearer token for authenticating with vLLM |
| `AGENT_VLLM_MODEL` | Yes | `default` | Model name as loaded in vLLM (e.g., `qwen3-coder-30b-awq4`) |
| `AGENT_PROXY_HOST` | No | `0.0.0.0` | Host address the proxy binds to |
| `AGENT_PROXY_PORT` | No | `8080` | Port the proxy listens on |
| `AGENT_WORKSPACE_DIR` | Yes | `/home/ubuntu/workspace` | Absolute path to the project directory the agent operates on |
| `AGENT_REQUIRE_APPROVAL` | No | `true` | Whether dangerous tools need human approval |
| `AGENT_MAX_AGENT_ITERATIONS` | No | `50` | Maximum LLM loop iterations (safety limit) |
| `AGENT_WATCH_ENABLED` | No | `true` | Enable real-time file change tracking |
| `AGENT_SANDBOX_ENABLED` | No | `false` | Enable sandbox testing validation loop |
| `AGENT_SANDBOX_MAX_ITERATIONS` | No | `2` | Max sandbox test retry iterations |
| `AGENT_REVIEW_ENABLED` | No | `false` | Enable planning review validation loop |
| `AGENT_REVIEW_MAX_ITERATIONS` | No | `2` | Max planning review iterations |

**Example `.env`:**

```env
# vLLM Connection
AGENT_VLLM_BASE_URL=http://35.153.222.132:8080/v1
AGENT_VLLM_API_KEY=ak-Qwen-30b-vllm-ec2
AGENT_VLLM_MODEL=qwen3-coder-30b-awq4

# Proxy Settings
AGENT_PROXY_HOST=0.0.0.0
AGENT_PROXY_PORT=8080

# Workspace (absolute path to the project directory)
AGENT_WORKSPACE_DIR=/home/ubuntu/my-project

# Agent Behavior
AGENT_REQUIRE_APPROVAL=true
AGENT_MAX_AGENT_ITERATIONS=50

# File Watcher
AGENT_WATCH_ENABLED=true

# Validation Loops (optional, increases quality but adds latency)
AGENT_SANDBOX_ENABLED=true
AGENT_SANDBOX_MAX_ITERATIONS=2
AGENT_REVIEW_ENABLED=true
AGENT_REVIEW_MAX_ITERATIONS=2
```

### Dangerous Tools & Approval

When `AGENT_REQUIRE_APPROVAL=true`, the following tools require explicit user approval before execution:

| Tool | Why It's Dangerous |
|---|---|
| `shell_execute` | Arbitrary command execution |
| `file_write` | Creates/overwrites files |
| `file_edit` | Modifies existing files |
| `file_delete` | Deletes files or directories |
| `run_tests` | Executes test suites (may have side effects) |

The approval flow works as follows:
1. Agent decides to call a dangerous tool
2. Proxy streams a formatted approval message to the client
3. User replies "yes" (approve) or "no" (deny)
4. Proxy resumes the agent with the result or denial message

### File Watcher

When enabled (`AGENT_WATCH_ENABLED=true`), the proxy monitors the workspace directory for file changes in real-time and injects a summary of recent changes into the agent's context on each new request.

**Ignored patterns** (hardcoded in `config.py`):
- `**/.git/**`
- `**/node_modules/**`
- `**/__pycache__/**`
- `**/.venv/**`

The watcher stores the last 100 changes and injects the last 20 into context.

### Validation Loops

Two optional validation loops run internally *before* the final response reaches the user:

**1. Sandbox Testing Loop** (`AGENT_SANDBOX_ENABLED=true`)
- After the agent makes code changes, a separate validation agent runs the code/tests
- If errors are found, it fixes them automatically
- Repeats up to `AGENT_SANDBOX_MAX_ITERATIONS` times
- Only passes output to user when execution succeeds

**2. Planning Review Loop** (`AGENT_REVIEW_ENABLED=true`)
- A separate review agent critically evaluates the code changes
- Checks for: logic errors, edge cases, performance issues, simpler approaches, security issues
- Applies improvements directly if found
- Repeats up to `AGENT_REVIEW_MAX_ITERATIONS` times

---

## Running the Project

```bash
# Development (with hot-reload)
python run.py

# The server starts at:
#   http://0.0.0.0:8080 (or whatever AGENT_PROXY_HOST:AGENT_PROXY_PORT is set to)

# Verify it's running:
curl http://localhost:8080/health
# Response: {"status":"ok","workspace":"/path/to/workspace"}
```

The development server uses `uvicorn` with `reload=True`, so any code changes will automatically restart the server.

---

## API Reference

### POST /v1/chat/completions

OpenAI-compatible chat completions endpoint. This is the main entry point for all interactions.

**Request Body:**

```json
{
  "model": "dev-agent",
  "messages": [
    {"role": "system", "content": "Optional system message"},
    {"role": "user", "content": "Create a hello world Python script"}
  ],
  "stream": true,
  "temperature": 0.1,
  "max_tokens": 4096
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | string | `"agent"` | Model name (ignored, always uses configured vLLM model) |
| `messages` | array | required | Chat messages in OpenAI format |
| `stream` | boolean | `true` | Whether to stream via SSE |
| `temperature` | float | `null` | Sampling temperature (overridden internally to 0.1) |
| `max_tokens` | int | `null` | Max output tokens (overridden internally to 4096) |

**Streaming Response (SSE):**

```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1234567890,"model":"dev-agent","choices":[{"index":0,"delta":{"content":"Hello! "},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1234567890,"model":"dev-agent","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

**Non-Streaming Response:**

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "dev-agent",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Done! I created hello.py."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

### GET /v1/models

Lists available models (returns a single "dev-agent" model).

```json
{
  "object": "list",
  "data": [
    {
      "id": "dev-agent",
      "object": "model",
      "created": 1234567890,
      "owned_by": "dev-agent-proxy"
    }
  ]
}
```

### GET /v1/pending

Lists all conversations currently suspended waiting for user approval.

```json
{
  "pending": [
    {
      "conv_key": "-123456789",
      "tool": "shell_execute",
      "arguments": {"command": "rm -rf build/"}
    }
  ]
}
```

### GET /health

Health check endpoint.

```json
{"status": "ok", "workspace": "/home/ubuntu/my-project"}
```

---

## Continue IDE Integration

1. Install the [Continue extension](https://continue.dev/) in VS Code

2. Open Continue settings (`~/.continue/config.json` or via the Continue settings UI)

3. Add the Dev Agent Proxy as a model:

```json
{
  "models": [
    {
      "title": "Dev Agent",
      "provider": "openai",
      "model": "dev-agent",
      "apiBase": "http://YOUR_PROXY_IP:8080/v1",
      "apiKey": "not-needed"
    }
  ],
  "tabAutocompleteModel": {
    "title": "vLLM Direct (for autocomplete)",
    "provider": "openai",
    "model": "YOUR_MODEL_NAME",
    "apiBase": "http://YOUR_VLLM_IP:8000/v1",
    "apiKey": "EMPTY"
  }
}
```

**Notes:**
- Replace `YOUR_PROXY_IP` with the IP/hostname where the proxy is running
- The `apiKey` field is required by Continue but not validated by the proxy — any value works
- For tab autocomplete, point directly to vLLM (bypasses the agent proxy for speed)
- A full example config is at `deploy/continue-config-example.json`

---

## How the Agent Works

### Agent Loop

The core logic lives in `app/core/agent_loop.py`. Each user message triggers this flow:

```
User Message
    │
    ▼
┌─ Agent Loop (max 50 iterations) ─────────────────────────┐
│                                                           │
│  1. Inject system prompt + file watcher context           │
│  2. Call vLLM with messages + tool schemas                │
│  3. Parse response:                                       │
│     ├── Native tool_calls? → Use them                     │
│     ├── Text-embedded tool calls? → Parse them (fallback) │
│     └── No tool calls? → Return text as final response    │
│  4. For each tool call:                                   │
│     ├── Dangerous? → Suspend & ask for approval           │
│     └── Safe? → Execute immediately                       │
│  5. Append tool result to messages                        │
│  6. Loop back to step 2                                   │
│                                                           │
└───────────────────────────────────────────────────────────┘
    │
    ▼
Final Response → Streamed to client as SSE
```

### Tool Calling Modes

The proxy supports two modes of tool calling, with automatic fallback:

**1. Native Function Calling (preferred)**
- Sends `tools` and `tool_choice` in the vLLM API request
- vLLM returns structured `tool_calls` in the response
- Used when the model supports OpenAI-compatible function calling

**2. Prompt-Based Fallback (automatic)**
- Activated when native calling returns a 400 error or a tool-related error
- Injects tool descriptions into the system prompt
- Parses tool calls from the model's text output
- Supports multiple formats:
  - **Qwen-style**: `<tool_call><function=name><parameter=key>value</parameter></function></tool_call>`
  - **JSON in `<tool_call>` tags**: `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`
  - **JSON code blocks**: ````json\n{"tool": "name", "arguments": {...}}\n````
  - **Trailing JSON objects**: `{...}` at the end of text

### Available Tools

| Tool | Description | Parameters |
|---|---|---|
| `file_read` | Read file contents with line numbers | `path` (required), `offset`, `limit` |
| `file_write` | Create or overwrite a file | `path` (required), `content` (required) |
| `file_edit` | Replace an exact string in a file | `path`, `old_string`, `new_string` (all required) |
| `file_delete` | Delete a file or directory | `path` (required), `recursive` |
| `glob_search` | Find files by glob pattern | `pattern` (required), `path` |
| `grep_search` | Search file contents with regex | `pattern` (required), `path`, `include`, `ignore_case` |
| `list_directory` | List directory contents | `path`, `recursive` |
| `shell_execute` | Run a shell command | `command` (required), `timeout`, `cwd` |
| `run_tests` | Run test suite (auto-detects framework) | `test_path`, `framework`, `verbose` |
| `request_approval` | Ask the user a question | `question` (required), `options` |

**Path Resolution:** All paths can be absolute or relative to `AGENT_WORKSPACE_DIR`.

**Test Framework Auto-Detection:**
- `pytest.ini` or `pyproject.toml` → pytest
- `package.json` with jest in test script → jest
- `package.json` with mocha in test script → mocha
- `go.mod` → go test
- `Cargo.toml` → cargo test

### Approval Workflow

When `AGENT_REQUIRE_APPROVAL=true` and the agent calls a dangerous tool:

1. The proxy **suspends** the agent loop and saves its full state (messages history, pending tool call)
2. The proxy streams a formatted approval message to the client:
   ```
   **Approval required** for `shell_execute`:
   ```json
   {"command": "rm -rf build/"}
   ```
   Reply **yes** to approve or **no** to deny.
   ```
3. The client (Continue) shows this to the user
4. The user replies with their next message
5. The proxy detects this is a response to a suspended session (via conversation key matching)
6. If approved: executes the tool and resumes the agent loop
7. If denied: injects "User denied this action" as the tool result and resumes

**Denial keywords**: `no`, `deny`, `reject`, `cancel`, `n` — anything else is treated as approval.

### Validation Loops

Internal validation agents that run *before* the response reaches the user (see `app/core/validation_loops.py`):

**Sandbox Testing:**
- Receives list of files the main agent changed
- Runs code/tests to verify correctness
- If failures found: fixes them and re-runs
- Passes only when execution succeeds or max iterations reached

**Planning Review:**
- Reads the changed files and the agent's summary
- Critically evaluates: logic errors, edge cases, performance, security
- Applies improvements directly via `file_edit`
- Pragmatic: only suggests meaningful changes

Both validation agents:
- Use the same vLLM backend as the main agent
- Have full access to all tools (except `request_approval`)
- Auto-fallback to prompt mode if native tool calling isn't available
- Are limited to 20 internal tool-call steps per iteration

---

## vLLM Backend Setup

The proxy requires a vLLM server running an instruction-tuned model. Below is the exact command used to host the model for this project:

### Production Command

```bash
# Install vLLM (requires NVIDIA GPU with CUDA)
pip install vllm

# Serve Qwen3 Coder 30B (AWQ 4-bit quantized, 4x GPU)
unset VLLM_ATTENTION_BACKEND && python -m vllm.entrypoints.openai.api_server \
  --model cpatonn/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit \
  --served-model-name qwen3-coder-30b-awq4 \
  --host 0.0.0.0 \
  --port 8080 \
  --dtype auto \
  --tensor-parallel-size 4 \
  --pipeline-parallel-size 1 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 16 \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser hermes

# Verify it's running
curl http://localhost:8080/v1/models
```

### Command Breakdown

| Flag | Value | Purpose |
|---|---|---|
| `--model` | `cpatonn/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | HuggingFace model ID (AWQ 4-bit quantized) |
| `--served-model-name` | `qwen3-coder-30b-awq4` | Name exposed via the API (must match `AGENT_VLLM_MODEL` in `.env`) |
| `--host` | `0.0.0.0` | Listen on all interfaces |
| `--port` | `8080` | Port for the OpenAI-compatible API |
| `--dtype` | `auto` | Auto-detect dtype from model config |
| `--tensor-parallel-size` | `4` | Shard model across 4 GPUs |
| `--pipeline-parallel-size` | `1` | No pipeline parallelism |
| `--gpu-memory-utilization` | `0.90` | Use 90% of GPU memory for KV cache |
| `--max-num-seqs` | `16` | Max concurrent sequences |
| `--enforce-eager` | — | Disable CUDA graph capture (more stable, slightly slower) |
| `--enable-auto-tool-choice` | — | Enable native function/tool calling support |
| `--tool-call-parser` | `hermes` | Use Hermes-style tool call parsing format |

### Important Notes

- **`unset VLLM_ATTENTION_BACKEND`** is required to avoid conflicts with custom attention backends that may be set in the environment
- **`--enable-auto-tool-choice` + `--tool-call-parser hermes`** enables native OpenAI-compatible tool calling — this is what allows the proxy to send `tools` in the request and receive structured `tool_calls` in the response
- **4 GPUs required** due to `--tensor-parallel-size 4` — adjust based on your hardware (e.g., use `2` for 2x GPUs)
- **`--enforce-eager`** trades some throughput for stability — remove it if you want CUDA graph optimization but may encounter OOM issues
- The proxy overrides `temperature=0.1` and `max_tokens=4096` regardless of client settings
- If native tool calling fails for any reason, the proxy auto-falls back to prompt-based tool calling (parses tool calls from text output)
- Ensure your `AGENT_VLLM_BASE_URL` in `.env` matches the host:port where vLLM is running (e.g., `http://YOUR_EC2_IP:8080/v1`)

### Hardware Requirements

For `Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` with the above config:
- **Minimum**: 4x NVIDIA GPUs with 16GB+ VRAM each (e.g., 4x T4, 4x A10G)
- **Recommended**: 4x A10G (24GB) or 2x A100 (80GB, reduce tensor-parallel-size to 2)
- **RAM**: 64GB+ system memory
- **Storage**: ~20GB for model weights

---

## Development Guide

### Adding a New Tool

1. **Define the schema** in `app/core/tool_schemas.py`:

```python
{
    "type": "function",
    "function": {
        "name": "my_new_tool",
        "description": "What this tool does",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."},
            },
            "required": ["param1"],
        },
    },
},
```

2. **Implement the tool** in `app/tools/filesystem.py` or `app/tools/shell.py` (or create a new file):

```python
def my_new_tool(param1: str) -> str:
    # Implementation
    return "result string"
```

3. **Register in the dispatcher** in `app/tools/dispatcher.py`:

```python
case "my_new_tool":
    return my_new_tool(
        param1=arguments["param1"],
    )
```

4. **Optionally add to dangerous_tools** in `app/core/config.py` if it has side effects:

```python
dangerous_tools: list[str] = [
    "shell_execute",
    "file_write",
    "file_edit",
    "file_delete",
    "run_tests",
    "my_new_tool",  # Add here if dangerous
]
```

5. **Add argument formatting** in `app/core/agent_loop.py` in the `_format_args` function:

```python
case "my_new_tool":
    return f"param1=`{arguments.get('param1', '?')}`"
```

### Modifying the Agent Prompt

The system prompt is defined at the top of `app/core/agent_loop.py` in the `SYSTEM_PROMPT` variable. Key aspects:
- Instructs the agent to always write code to files (never just display it)
- Tells it to read files before editing
- Encourages using search tools before making changes
- Sets the workspace directory context

### Testing Changes

Since the project doesn't have a formal test suite yet, test changes by:

1. Start the dev server: `python run.py`
2. Use curl to test the health endpoint:
   ```bash
   curl http://localhost:8080/health
   ```
3. Use curl to test a chat completion:
   ```bash
   curl -X POST http://localhost:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "dev-agent",
       "messages": [{"role": "user", "content": "List files in the workspace"}],
       "stream": false
     }'
   ```
4. Test streaming with:
   ```bash
   curl -N -X POST http://localhost:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "dev-agent",
       "messages": [{"role": "user", "content": "Read the README file"}],
       "stream": true
     }'
   ```
5. Or connect Continue IDE to `http://localhost:8080/v1` and interact naturally

---

## Troubleshooting

### Proxy won't start

- **Port already in use**: Change `AGENT_PROXY_PORT` in `.env` or kill the process using that port
- **Module not found errors**: Ensure you activated the virtual environment (`source .venv/bin/activate`)
- **`.env` not loading**: The file must be in the project root directory (same as `run.py`)

### Agent not responding / hanging

- **vLLM unreachable**: Check `AGENT_VLLM_BASE_URL` is correct and the vLLM server is running
  ```bash
  curl http://YOUR_VLLM_IP:PORT/v1/models
  ```
- **Timeout**: The default HTTP timeout is 300 seconds. Large prompts or slow GPUs may need more time.
- **Max iterations reached**: If the agent hits the 50-iteration limit, increase `AGENT_MAX_AGENT_ITERATIONS` or simplify the task

### Tool calls not being parsed

- **Model doesn't support native tool calling**: The proxy should auto-fallback to prompt mode. Check the logs for "400" or "tool" errors.
- **Qwen-format not detected**: Ensure the model outputs `<tool_call>` tags. Try a different model or adjust the system prompt.

### Approval not working

- **Session mismatch**: The approval system matches conversations by hashing the first user message. If Continue sends messages differently between turns, the match fails.
- **Multiple pending**: Check `/v1/pending` to see all suspended sessions.

### File watcher issues

- **Permission denied**: Ensure the proxy process has read access to `AGENT_WORKSPACE_DIR`
- **Too many changes**: The watcher caps at 100 stored changes and injects only the last 20

### Windows-specific issues

- **Path separators**: Use either `/` or `\\` in `AGENT_WORKSPACE_DIR` (Python handles both)
- **Shell commands**: `shell_execute` uses the system's default shell. On Windows, this is `cmd.exe` via `asyncio.create_subprocess_shell`
- **File watching**: `watchfiles` works on Windows but may have slightly higher latency

---

## Git & Contributing

### Initial Setup (Push to GitHub)

```bash
# Initialize git (if not already)
cd CodeCom-Continue-V2  # or dev-agent-proxy
git init

# Add the remote
git remote add origin https://github.com/Ananth2308/CodeCom-Continue-V2.git

# Verify .gitignore excludes sensitive files
cat .gitignore
# Should include: .venv/, __pycache__/, *.pyc, .env, *.egg-info/, dist/, build/

# Stage all files
git add .

# Verify no secrets are staged
git status
# IMPORTANT: Ensure .env is NOT listed (it contains API keys)

# Commit
git commit -m "Initial commit: Dev Agent Proxy with tool use and approval workflow"

# Push
git branch -M main
git push -u origin main
```

### For Future Development

```bash
# Pull latest changes
git pull origin main

# Create a feature branch
git checkout -b feature/my-feature

# Make changes, then:
git add .
git commit -m "Add: description of changes"
git push -u origin feature/my-feature

# Create a Pull Request on GitHub
```

### What's in `.gitignore`

```
.venv/          # Virtual environment (reinstall from requirements.txt)
__pycache__/    # Python bytecode cache
*.pyc           # Compiled Python files
.env            # Contains API keys and secrets — NEVER COMMIT
*.egg-info/     # Package metadata
dist/           # Distribution builds
build/          # Build artifacts
```

### Security Warning

**NEVER commit the `.env` file.** It contains:
- `AGENT_VLLM_API_KEY` — Your vLLM authentication token
- `AGENT_VLLM_BASE_URL` — Your server's IP address
- `AGENT_WORKSPACE_DIR` — Local filesystem paths

If you accidentally commit it:
```bash
git rm --cached .env
git commit -m "Remove .env from tracking"
# Then rotate your API keys immediately
```

---

## Dependencies

All Python dependencies with their purposes:

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | >=0.104.0 | Web framework for the proxy API |
| `uvicorn[standard]` | >=0.24.0 | ASGI server (runs FastAPI) |
| `httpx` | >=0.25.0 | Async HTTP client (calls vLLM API) |
| `pydantic` | >=2.5.0 | Data validation for request/response models |
| `pydantic-settings` | >=2.1.0 | Environment-based configuration |
| `watchfiles` | >=0.21.0 | Real-time file system monitoring |
| `python-dotenv` | >=1.0.0 | Load `.env` files into environment |
| `sse-starlette` | >=1.8.0 | Server-Sent Events for streaming |

Install all with: `pip install -r requirements.txt`

---

## License

This project is not yet licensed. Contact the repository owner for usage terms.
