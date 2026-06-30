"""Fallback tool-call parser for models without native function calling.

When native tool calling is not supported, the agent loop can switch to a
prompt-based approach where the model outputs tool calls in a structured format.
This module parses those outputs.

Supported formats:
1. Qwen-style: <tool_call>\n<function=name>\n<parameter=key>value</parameter>\n</tool_call>
2. JSON inside <tool_call>: <tool_call>\n{"name": "...", "arguments": {...}}\n</tool_call>
3. JSON code block: ```json\n{"tool": "name", "arguments": {...}}\n```
4. Direct JSON with "tool_calls" key
"""

import json
import re
from typing import Optional


def parse_tool_calls_from_text(text: str) -> tuple[str, list[dict]]:
    """Parse tool calls from model output text.

    Returns:
        (clean_text, tool_calls) where clean_text is the text with tool call
        blocks removed, and tool_calls is a list of parsed tool calls in
        OpenAI format.
    """
    tool_calls = []
    clean_text = text

    # Try Qwen-style format: <tool_call>\n<function=name>\n<parameter=key>value\n</tool_call>
    qwen_pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
    qwen_matches = re.findall(qwen_pattern, text, re.DOTALL)
    if qwen_matches:
        for i, match in enumerate(qwen_matches):
            # Try Qwen format first: <function=name><parameter=key>value</parameter>
            tc = _parse_qwen_tool_call(match, f"call_{i}")
            if tc:
                tool_calls.append(tc)
            else:
                # Fall back to JSON inside <tool_call>
                parsed = _try_parse_json(match)
                if parsed:
                    tc = _normalize_tool_call(parsed, f"call_{i}")
                    if tc:
                        tool_calls.append(tc)
        clean_text = re.sub(qwen_pattern, "", text, flags=re.DOTALL).strip()
        if tool_calls:
            return clean_text, tool_calls

    # Try JSON code block format: ```json\n{...}\n```
    json_block_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    json_matches = re.findall(json_block_pattern, text, re.DOTALL)
    for i, match in enumerate(json_matches):
        parsed = _try_parse_json(match)
        if parsed and _looks_like_tool_call(parsed):
            tc = _normalize_tool_call(parsed, f"call_{i}")
            if tc:
                tool_calls.append(tc)

    if tool_calls:
        clean_text = re.sub(json_block_pattern, "", text, flags=re.DOTALL).strip()
        return clean_text, tool_calls

    # Try direct JSON object at end of text
    json_at_end = re.search(r"\{[^{}]*\"(?:tool|function|name)\"[^{}]*\}\s*$", text)
    if json_at_end:
        parsed = _try_parse_json(json_at_end.group())
        if parsed and _looks_like_tool_call(parsed):
            tc = _normalize_tool_call(parsed, "call_0")
            if tc:
                tool_calls.append(tc)
                clean_text = text[: json_at_end.start()].strip()

    return clean_text, tool_calls


def build_tool_prompt_suffix(tool_schemas: list[dict]) -> str:
    """Build a system prompt suffix that instructs the model to use tools via text."""
    tools_desc = []
    for schema in tool_schemas:
        func = schema["function"]
        params = json.dumps(func["parameters"], indent=2)
        tools_desc.append(
            f"### {func['name']}\n{func['description']}\nParameters:\n```json\n{params}\n```"
        )

    return f"""
## Available Tools

You have access to the following tools. To use a tool, output a tool call in this exact format:

<tool_call>
<function=tool_name>
<parameter=param1>value1</parameter>
<parameter=param2>value2</parameter>
</function>
</tool_call>

You may output text before and after tool calls. You can make multiple tool calls in one response.

After each tool call, you will receive the result. Continue calling tools until the task is complete, then provide your final answer without any tool calls.

{chr(10).join(tools_desc)}
"""


def _parse_qwen_tool_call(text: str, call_id: str) -> Optional[dict]:
    """Parse Qwen-style tool call format:
    <function=tool_name>
    <parameter=param1>value1</parameter>
    <parameter=param2>value2</parameter>
    """
    # Match <function=name> with optional content after
    func_match = re.search(r"<function=([^>]+)>", text)
    if not func_match:
        return None

    func_name = func_match.group(1).strip()

    # Extract parameters: <parameter=key>value</parameter>
    # Also handle <parameter=key>value (without closing tag)
    param_pattern = r"<parameter=([^>]+)>(.*?)(?:</parameter>|(?=<parameter=)|$)"
    params = re.findall(param_pattern, text, re.DOTALL)

    arguments = {}
    for key, value in params:
        key = key.strip()
        value = value.strip()
        # Try to parse value as JSON (for numbers, booleans, objects)
        try:
            arguments[key] = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            arguments[key] = value

    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": func_name,
            "arguments": json.dumps(arguments),
        },
    }


def _try_parse_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _looks_like_tool_call(obj: dict) -> bool:
    return any(
        key in obj for key in ("tool", "function", "name", "tool_calls", "tool_call")
    )


def _normalize_tool_call(parsed: dict, call_id: str) -> Optional[dict]:
    """Normalize various tool call formats into OpenAI format."""
    name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
    arguments = parsed.get("arguments") or parsed.get("params") or parsed.get("parameters") or {}

    if isinstance(name, dict):
        # Handle {"function": {"name": "...", "arguments": ...}}
        arguments = name.get("arguments", arguments)
        name = name.get("name")

    if not name or not isinstance(name, str):
        return None

    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments) if isinstance(arguments, dict) else str(arguments),
        },
    }
