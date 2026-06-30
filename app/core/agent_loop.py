import json
import httpx
from typing import AsyncGenerator
from app.core.config import settings
from app.core.tool_schemas import TOOL_SCHEMAS
from app.core.tool_parser import parse_tool_calls_from_text, build_tool_prompt_suffix
from app.tools.dispatcher import dispatch_tool

SYSTEM_PROMPT = """You are a software development agent with full access to the project workspace.
You can read, write, and edit files, search the codebase, run shell commands, and execute tests.

## Critical Rules
- ALWAYS write code to files using file_write or file_edit. NEVER just display code in your response.
- When asked to create code, write it to an appropriate file in the workspace.
- When asked to modify code, use file_edit on the existing file.
- Read files before editing them to understand context.
- Use file_edit for surgical changes (prefer over file_write for existing files).
- Use grep_search and glob_search to find relevant code before making changes.
- Run tests after making changes to verify correctness.
- If unsure about a destructive action, use request_approval to ask the user.
- Keep changes minimal and focused on the task at hand.
- Do not add unnecessary comments or documentation unless asked.

## Workspace
Your workspace directory is: {workspace_dir}
All relative paths are resolved against this directory.
""".format(workspace_dir=settings.workspace_dir)


class AgentLoop:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=300.0)
        self._use_prompt_mode: bool = False

    async def run(self, messages: list[dict]) -> AsyncGenerator[str | dict, None]:
        """Run the agent loop, yielding text chunks or approval-needed dicts."""

        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        async for event in self._loop(full_messages):
            yield event

    async def resume(
        self, messages_so_far: list[dict], tool_call: dict, approved: bool
    ) -> AsyncGenerator[str | dict, None]:
        """Resume after an approval decision."""

        func_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])

        if approved:
            result = await dispatch_tool(func_name, arguments)
            yield f"Executed `{func_name}` successfully.\n"
        else:
            result = "User denied this action."

        messages_so_far.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": result,
        })

        async for event in self._loop(messages_so_far):
            yield event

    async def _loop(self, full_messages: list[dict]) -> AsyncGenerator[str | dict, None]:
        """Core agent loop that calls LLM, executes tools, and repeats."""

        iteration = 0
        while iteration < settings.max_agent_iterations:
            iteration += 1

            yield f"\n**[LLM Call #{iteration}]** Calling model...\n"

            response = await self._call_llm(full_messages)

            if response is None:
                yield "\n[Error: Failed to get response from LLM]\n"
                return

            assistant_message = response["choices"][0]["message"]

            # Show raw response info for debugging
            raw_content = assistant_message.get("content", "")
            has_native_tools = bool(assistant_message.get("tool_calls"))
            yield f"  Raw response: {len(raw_content)} chars, native tool_calls: {has_native_tools}\n"

            # Always try to parse tool calls from content
            tool_calls = assistant_message.get("tool_calls")
            if not tool_calls:
                content = assistant_message.get("content", "")
                if content:
                    clean_text, parsed_calls = parse_tool_calls_from_text(content)
                    if parsed_calls:
                        yield f"  Parsed {len(parsed_calls)} tool call(s) from text\n"
                        assistant_message["content"] = clean_text
                        assistant_message["tool_calls"] = parsed_calls
                        tool_calls = parsed_calls
                    else:
                        yield f"  No tool calls found in response\n"

            full_messages.append(assistant_message)

            if not tool_calls:
                content = assistant_message.get("content", "")
                if content:
                    yield f"\n**[Final Response]**\n{content}"
                return

            # Stream thinking/reasoning content before tool execution
            content = assistant_message.get("content", "")
            if content:
                yield f"\n**[Thinking]**\n{content}\n\n"

            # Execute each tool call
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                # Build a readable summary of the arguments
                args_summary = _format_args(func_name, arguments)

                # Check if this tool needs approval — suspend if so
                if settings.require_approval and func_name in settings.dangerous_tools:
                    yield f"\n**[Tool Call]** `{func_name}`\n"
                    yield f"  Arguments: {args_summary}\n"
                    yield f"  Status: Waiting for approval...\n"
                    yield {
                        "type": "approval_needed",
                        "messages_so_far": full_messages,
                        "tool_call": tc,
                    }
                    return

                elif func_name == "request_approval":
                    yield f"\n**[Asking User]** {arguments.get('question', '')}\n"
                    yield {
                        "type": "approval_needed",
                        "messages_so_far": full_messages,
                        "tool_call": tc,
                    }
                    return

                else:
                    # Safe tool — execute and show result
                    yield f"\n**[Tool Call]** `{func_name}`\n"
                    yield f"  Arguments: {args_summary}\n"
                    result = await dispatch_tool(func_name, arguments)
                    # Show truncated result
                    result_preview = result[:500] if len(result) > 500 else result
                    yield f"  Result: {result_preview}\n"

                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

        yield "\n[Agent reached maximum iterations]\n"

    async def _call_llm(self, messages: list[dict]) -> dict | None:
        """Call the vLLM endpoint."""
        payload = {
            "model": settings.vllm_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        if not self._use_prompt_mode:
            payload["tools"] = TOOL_SCHEMAS
            payload["tool_choice"] = "auto"

        try:
            resp = await self.client.post(
                f"{settings.vllm_base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
            )
            resp.raise_for_status()
            result = resp.json()

            if not self._use_prompt_mode:
                error = result.get("error")
                if error and "tool" in str(error).lower():
                    self._use_prompt_mode = True
                    return await self._call_llm_prompt_mode(messages)

            if self._use_prompt_mode:
                return self._parse_prompt_mode_response(result)

            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and not self._use_prompt_mode:
                self._use_prompt_mode = True
                return await self._call_llm_prompt_mode(messages)
            print(f"LLM API error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            print(f"LLM connection error: {e}")
            return None

    async def _call_llm_prompt_mode(self, messages: list[dict]) -> dict | None:
        """Call LLM with tools described in the system prompt."""
        augmented = []
        for msg in messages:
            if msg["role"] == "system":
                augmented.append({
                    "role": "system",
                    "content": msg["content"] + build_tool_prompt_suffix(TOOL_SCHEMAS),
                })
            else:
                augmented.append(msg)

        payload = {
            "model": settings.vllm_model,
            "messages": augmented,
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        try:
            resp = await self.client.post(
                f"{settings.vllm_base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
            )
            resp.raise_for_status()
            return self._parse_prompt_mode_response(resp.json())
        except Exception as e:
            print(f"LLM prompt-mode error: {e}")
            return None

    def _parse_prompt_mode_response(self, response: dict) -> dict:
        """Parse tool calls embedded in text."""
        message = response["choices"][0]["message"]
        content = message.get("content", "")

        clean_text, tool_calls = parse_tool_calls_from_text(content)
        if tool_calls:
            message["content"] = clean_text
            message["tool_calls"] = tool_calls

        return response

    async def close(self):
        await self.client.aclose()


def _format_args(func_name: str, arguments: dict) -> str:
    """Format tool arguments into a readable one-line summary."""
    match func_name:
        case "file_read":
            path = arguments.get("path", "?")
            extra = ""
            if "offset" in arguments:
                extra += f", from line {arguments['offset']}"
            if "limit" in arguments:
                extra += f", {arguments['limit']} lines"
            return f"path=`{path}`{extra}"
        case "file_write":
            path = arguments.get("path", "?")
            content = arguments.get("content", "")
            return f"path=`{path}`, content=({len(content)} chars)"
        case "file_edit":
            path = arguments.get("path", "?")
            old = arguments.get("old_string", "")[:50]
            new = arguments.get("new_string", "")[:50]
            return f"path=`{path}`, replacing `{old}...` → `{new}...`"
        case "file_delete":
            return f"path=`{arguments.get('path', '?')}`"
        case "glob_search":
            return f"pattern=`{arguments.get('pattern', '?')}`"
        case "grep_search":
            pattern = arguments.get("pattern", "?")
            path = arguments.get("path", "workspace")
            return f"pattern=`{pattern}`, in=`{path}`"
        case "shell_execute":
            cmd = arguments.get("command", "?")
            return f"command=`{cmd}`"
        case "run_tests":
            path = arguments.get("test_path", "all")
            fw = arguments.get("framework", "auto")
            return f"tests=`{path}`, framework={fw}"
        case "list_directory":
            path = arguments.get("path", "workspace root")
            return f"path=`{path}`"
        case _:
            return json.dumps(arguments, indent=2)[:200]
