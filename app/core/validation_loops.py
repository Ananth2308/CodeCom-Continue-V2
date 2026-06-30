"""Internal validation loops that run BEFORE output reaches the user.

1. Sandbox Testing Loop (max 2 iterations):
   - Runs the generated code / tests
   - If errors found, asks LLM to fix
   - Only passes if execution succeeds or max retries hit

2. Planning Review Loop (max 2 iterations):
   - Challenges the output: can it be better?
   - If improvements identified, asks LLM to apply them
   - Produces the final polished output
"""

import json
import httpx
from typing import AsyncGenerator
from app.core.config import settings
from app.core.tool_schemas import TOOL_SCHEMAS
from app.core.tool_parser import parse_tool_calls_from_text, build_tool_prompt_suffix
from app.tools.dispatcher import dispatch_tool


SANDBOX_TEST_PROMPT = """You are a code testing agent. Your job is to verify that the code changes just made are correct and working.

## What was done
The following files were modified during this session:
{files_changed}

## Your task
1. Run the code or tests to verify correctness.
2. If there are syntax errors, runtime errors, or test failures, FIX them.
3. If everything passes, respond with exactly: SANDBOX_PASS
4. If you made fixes, describe what you fixed briefly, then end with: SANDBOX_PASS

Use the available tools to run and fix the code. Do NOT ask for user approval — just fix issues directly.

## Workspace
{workspace_dir}
"""

PLANNING_REVIEW_PROMPT = """You are a code review agent. Challenge the solution and look for improvements.

## What was done
The following changes were made:
{summary}

## Files changed
{files_changed}

## Your task
Review the code critically. Look for:
- Logic errors or edge cases not handled
- Performance issues
- Simpler or more elegant approaches
- Missing error handling at system boundaries
- Security issues

If you find improvements worth making:
1. Apply them using the available tools (file_edit)
2. Describe what you improved
3. End with: REVIEW_IMPROVED

If the code is already good and no meaningful improvements are needed:
- End with: REVIEW_PASS

Be pragmatic — only suggest changes that meaningfully improve the code. Do not add unnecessary comments, over-engineer, or refactor working code for style alone.

## Workspace
{workspace_dir}
"""


class ValidationRunner:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=300.0)
        self._use_prompt_mode: bool = False

    async def run_sandbox_test(
        self, files_changed: list[str], progress_callback=None
    ) -> dict:
        """Run sandbox testing loop. Returns {passed: bool, iterations: int, fixes: str}."""

        if not files_changed:
            return {"passed": True, "iterations": 0, "fixes": ""}

        all_fixes = []

        for iteration in range(settings.sandbox_max_iterations):
            if progress_callback:
                await progress_callback(
                    f"[Sandbox Test {iteration + 1}/{settings.sandbox_max_iterations}] Running...\n"
                )

            prompt = SANDBOX_TEST_PROMPT.format(
                files_changed="\n".join(f"  - {f}" for f in files_changed),
                workspace_dir=settings.workspace_dir,
            )

            result = await self._run_validation_agent(prompt)

            if "SANDBOX_PASS" in result:
                if progress_callback:
                    await progress_callback(
                        f"[Sandbox Test] Passed on iteration {iteration + 1}\n"
                    )
                return {
                    "passed": True,
                    "iterations": iteration + 1,
                    "fixes": "\n".join(all_fixes),
                }
            else:
                all_fixes.append(f"Iteration {iteration + 1}: {result[:500]}")
                if progress_callback:
                    await progress_callback(
                        f"[Sandbox Test] Issues found, fixing (attempt {iteration + 1})...\n"
                    )

        # Max iterations reached
        if progress_callback:
            await progress_callback(
                f"[Sandbox Test] Completed {settings.sandbox_max_iterations} iterations\n"
            )
        return {
            "passed": False,
            "iterations": settings.sandbox_max_iterations,
            "fixes": "\n".join(all_fixes),
        }

    async def run_planning_review(
        self, summary: str, files_changed: list[str], progress_callback=None
    ) -> dict:
        """Run planning review loop. Returns {improved: bool, iterations: int, changes: str}."""

        if not files_changed:
            return {"improved": False, "iterations": 0, "changes": ""}

        all_changes = []

        for iteration in range(settings.review_max_iterations):
            if progress_callback:
                await progress_callback(
                    f"[Planning Review {iteration + 1}/{settings.review_max_iterations}] Reviewing...\n"
                )

            # Read current state of changed files for context
            file_contents = await self._read_changed_files(files_changed)

            prompt = PLANNING_REVIEW_PROMPT.format(
                summary=summary,
                files_changed=file_contents,
                workspace_dir=settings.workspace_dir,
            )

            result = await self._run_validation_agent(prompt)

            if "REVIEW_PASS" in result:
                if progress_callback:
                    await progress_callback(
                        f"[Planning Review] Approved on iteration {iteration + 1}\n"
                    )
                return {
                    "improved": len(all_changes) > 0,
                    "iterations": iteration + 1,
                    "changes": "\n".join(all_changes),
                }
            elif "REVIEW_IMPROVED" in result:
                all_changes.append(f"Iteration {iteration + 1}: {result[:500]}")
                if progress_callback:
                    await progress_callback(
                        f"[Planning Review] Improvements applied (iteration {iteration + 1})\n"
                    )
            else:
                # No clear signal — treat as pass
                if progress_callback:
                    await progress_callback(
                        f"[Planning Review] Complete (iteration {iteration + 1})\n"
                    )
                return {
                    "improved": len(all_changes) > 0,
                    "iterations": iteration + 1,
                    "changes": "\n".join(all_changes),
                }

        return {
            "improved": len(all_changes) > 0,
            "iterations": settings.review_max_iterations,
            "changes": "\n".join(all_changes),
        }

    async def run_sandbox_test_streaming(
        self, files_changed: list[str]
    ) -> AsyncGenerator[str, None]:
        """Run sandbox testing with live streaming of tool calls."""
        if not files_changed:
            yield "No files to test.\n"
            return

        for iteration in range(settings.sandbox_max_iterations):
            yield f"  [Iteration {iteration + 1}/{settings.sandbox_max_iterations}]\n"

            prompt = SANDBOX_TEST_PROMPT.format(
                files_changed="\n".join(f"  - {f}" for f in files_changed),
                workspace_dir=settings.workspace_dir,
            )

            final_text = ""
            async for event in self._run_validation_agent_streaming(prompt):
                if event.get("type") == "tool_call":
                    yield f"    > `{event['name']}` {event.get('summary', '')} "
                elif event.get("type") == "tool_done":
                    yield "done\n"
                elif event.get("type") == "text":
                    final_text = event["content"]

            if "SANDBOX_PASS" in final_text:
                yield f"  PASSED\n"
                return
            else:
                yield f"  Issues found, fixing...\n"

        yield f"  Completed {settings.sandbox_max_iterations} iterations\n"

    async def run_planning_review_streaming(
        self, summary: str, files_changed: list[str]
    ) -> AsyncGenerator[str, None]:
        """Run planning review with live streaming of tool calls."""
        if not files_changed:
            yield "No files to review.\n"
            return

        for iteration in range(settings.review_max_iterations):
            yield f"  [Iteration {iteration + 1}/{settings.review_max_iterations}]\n"

            file_contents = await self._read_changed_files(files_changed)

            prompt = PLANNING_REVIEW_PROMPT.format(
                summary=summary,
                files_changed=file_contents,
                workspace_dir=settings.workspace_dir,
            )

            final_text = ""
            async for event in self._run_validation_agent_streaming(prompt):
                if event.get("type") == "tool_call":
                    yield f"    > `{event['name']}` {event.get('summary', '')} "
                elif event.get("type") == "tool_done":
                    yield "done\n"
                elif event.get("type") == "text":
                    final_text = event["content"]
                elif event.get("type") == "thinking":
                    yield f"    {event['content']}\n"

            if "REVIEW_PASS" in final_text:
                yield f"  Solution approved\n"
                return
            elif "REVIEW_IMPROVED" in final_text:
                yield f"  Improvements applied\n"
            else:
                yield f"  Complete\n"
                return

    async def _run_validation_agent_streaming(self, prompt: str) -> AsyncGenerator[dict, None]:
        """Run a validation agent, yielding events for each tool call and result."""

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Begin validation."},
        ]

        max_steps = 20
        for _ in range(max_steps):
            response = await self._call_llm(messages)
            if response is None:
                yield {"type": "text", "content": "Error: LLM call failed"}
                return

            assistant_message = response["choices"][0]["message"]

            tool_calls = assistant_message.get("tool_calls")
            if not tool_calls:
                content = assistant_message.get("content", "")
                if content:
                    clean_text, parsed_calls = parse_tool_calls_from_text(content)
                    if parsed_calls:
                        assistant_message["content"] = clean_text
                        assistant_message["tool_calls"] = parsed_calls
                        tool_calls = parsed_calls

            messages.append(assistant_message)

            if not tool_calls:
                content = assistant_message.get("content", "")
                if content:
                    yield {"type": "thinking", "content": content[:200]}
                yield {"type": "text", "content": assistant_message.get("content", "")}
                return

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                # Brief summary of what's being done
                summary = ""
                if "path" in arguments:
                    summary = arguments["path"]
                elif "command" in arguments:
                    summary = arguments["command"][:50]
                elif "pattern" in arguments:
                    summary = arguments["pattern"]

                yield {"type": "tool_call", "name": func_name, "summary": summary}

                if func_name == "request_approval":
                    result = "Skipped: validation agents cannot request user approval"
                else:
                    result = await dispatch_tool(func_name, arguments)

                yield {"type": "tool_done", "name": func_name}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        yield {"type": "text", "content": "Validation agent reached max steps"}

    async def _run_validation_agent(self, prompt: str) -> str:
        """Run a validation agent that can use tools. Returns final text output."""

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Begin validation."},
        ]

        max_steps = 20
        for _ in range(max_steps):
            response = await self._call_llm(messages)
            if response is None:
                return "Error: LLM call failed"

            assistant_message = response["choices"][0]["message"]

            # Parse tool calls from content if needed
            tool_calls = assistant_message.get("tool_calls")
            if not tool_calls:
                content = assistant_message.get("content", "")
                if content:
                    clean_text, parsed_calls = parse_tool_calls_from_text(content)
                    if parsed_calls:
                        assistant_message["content"] = clean_text
                        assistant_message["tool_calls"] = parsed_calls
                        tool_calls = parsed_calls

            messages.append(assistant_message)

            if not tool_calls:
                return assistant_message.get("content", "")

            # Execute tools (no approval needed — internal agent)
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                # Skip approval-only tools in validation context
                if func_name == "request_approval":
                    result = "Skipped: validation agents cannot request user approval"
                else:
                    result = await dispatch_tool(func_name, arguments)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        return "Validation agent reached max steps"

    async def _read_changed_files(self, files: list[str]) -> str:
        """Read contents of changed files for review context."""
        from app.tools.filesystem import file_read

        parts = []
        for f in files[:10]:  # Limit to 10 files
            content = file_read(f, limit=200)
            parts.append(f"### {f}\n```\n{content}\n```")
        return "\n\n".join(parts)

    async def _call_llm(self, messages: list[dict]) -> dict | None:
        """Call vLLM for validation agents."""
        payload = {
            "model": settings.vllm_model,
            "messages": messages,
            "temperature": 0.2,
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
                return self._parse_response(result)

            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and not self._use_prompt_mode:
                self._use_prompt_mode = True
                return await self._call_llm_prompt_mode(messages)
            return None
        except Exception:
            return None

    async def _call_llm_prompt_mode(self, messages: list[dict]) -> dict | None:
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
            "temperature": 0.2,
            "max_tokens": 4096,
        }

        try:
            resp = await self.client.post(
                f"{settings.vllm_base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
            )
            resp.raise_for_status()
            return self._parse_response(resp.json())
        except Exception:
            return None

    def _parse_response(self, response: dict) -> dict:
        message = response["choices"][0]["message"]
        content = message.get("content", "")
        clean_text, tool_calls = parse_tool_calls_from_text(content)
        if tool_calls:
            message["content"] = clean_text
            message["tool_calls"] = tool_calls
        return response

    async def close(self):
        await self.client.aclose()
