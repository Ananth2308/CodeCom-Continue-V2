import asyncio
import os
from app.core.config import settings


async def shell_execute(command: str, timeout: int = 120, cwd: str | None = None) -> str:
    work_dir = cwd if cwd and os.path.isdir(cwd) else settings.workspace_dir

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        output_parts = []
        if stdout:
            output_parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            output_parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace')}")

        output = "\n".join(output_parts)

        # Truncate very long output
        if len(output) > 30000:
            output = output[:15000] + "\n\n... (output truncated) ...\n\n" + output[-15000:]

        exit_info = f"[exit code: {proc.returncode}]"
        return f"{output}\n{exit_info}" if output else exit_info

    except asyncio.TimeoutError:
        proc.kill()
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {e}"


async def run_tests(
    test_path: str | None = None, framework: str = "auto", verbose: bool = False
) -> str:
    if framework == "auto":
        framework = _detect_framework()

    cmd = _build_test_command(framework, test_path, verbose)
    if not cmd:
        return f"Error: Could not determine test command for framework '{framework}'"

    return await shell_execute(cmd, timeout=300)


def _detect_framework() -> str:
    ws = settings.workspace_dir

    if os.path.exists(os.path.join(ws, "pytest.ini")) or os.path.exists(
        os.path.join(ws, "pyproject.toml")
    ):
        return "pytest"

    pkg_json = os.path.join(ws, "package.json")
    if os.path.exists(pkg_json):
        try:
            import json
            with open(pkg_json) as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                test_script = scripts["test"]
                if "jest" in test_script:
                    return "jest"
                if "mocha" in test_script:
                    return "mocha"
                return "jest"
        except Exception:
            pass

    if os.path.exists(os.path.join(ws, "go.mod")):
        return "go"

    if os.path.exists(os.path.join(ws, "Cargo.toml")):
        return "cargo"

    return "pytest"


def _build_test_command(framework: str, test_path: str | None, verbose: bool) -> str | None:
    v_flag = ""

    match framework:
        case "pytest":
            v_flag = " -v" if verbose else ""
            path_arg = f" {test_path}" if test_path else ""
            return f"python -m pytest{v_flag}{path_arg}"
        case "jest":
            v_flag = " --verbose" if verbose else ""
            path_arg = f" {test_path}" if test_path else ""
            return f"npx jest{v_flag}{path_arg}"
        case "mocha":
            path_arg = f" {test_path}" if test_path else ""
            return f"npx mocha{path_arg}"
        case "go":
            v_flag = " -v" if verbose else ""
            path_arg = f" ./{test_path}/..." if test_path else " ./..."
            return f"go test{v_flag}{path_arg}"
        case "cargo":
            path_arg = f" --test {test_path}" if test_path else ""
            return f"cargo test{path_arg}"
        case _:
            return None
