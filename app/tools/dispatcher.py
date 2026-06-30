import json
from app.tools.filesystem import (
    file_read,
    file_write,
    file_edit,
    file_delete,
    glob_search,
    grep_search,
    list_directory,
)
from app.tools.shell import shell_execute, run_tests


async def dispatch_tool(name: str, arguments: dict) -> str:
    match name:
        case "file_read":
            return file_read(
                path=arguments["path"],
                offset=arguments.get("offset", 0),
                limit=arguments.get("limit"),
            )
        case "file_write":
            return file_write(
                path=arguments["path"],
                content=arguments["content"],
            )
        case "file_edit":
            return file_edit(
                path=arguments["path"],
                old_string=arguments["old_string"],
                new_string=arguments["new_string"],
            )
        case "file_delete":
            return file_delete(
                path=arguments["path"],
                recursive=arguments.get("recursive", False),
            )
        case "glob_search":
            return glob_search(
                pattern=arguments["pattern"],
                path=arguments.get("path"),
            )
        case "grep_search":
            return grep_search(
                pattern=arguments["pattern"],
                path=arguments.get("path"),
                include=arguments.get("include"),
                ignore_case=arguments.get("ignore_case", False),
            )
        case "list_directory":
            return list_directory(
                path=arguments.get("path"),
                recursive=arguments.get("recursive", False),
            )
        case "shell_execute":
            return await shell_execute(
                command=arguments["command"],
                timeout=arguments.get("timeout", 120),
                cwd=arguments.get("cwd"),
            )
        case "run_tests":
            return await run_tests(
                test_path=arguments.get("test_path"),
                framework=arguments.get("framework", "auto"),
                verbose=arguments.get("verbose", False),
            )
        case "request_approval":
            # This is handled specially by the agent loop — should not reach here
            return "Error: request_approval should be handled by the agent loop"
        case _:
            return f"Error: Unknown tool '{name}'"
