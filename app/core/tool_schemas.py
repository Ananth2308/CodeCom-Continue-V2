TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file. Returns the file content with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path to the file",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (0-indexed). Optional.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read. Optional.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path to the file",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": "Edit a file by replacing a specific string with a new string. The old_string must match exactly (including whitespace/indentation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path to the file",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact string to find and replace",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The replacement string",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_delete",
            "description": "Delete a file or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path to delete",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, recursively delete directories. Default false.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_search",
            "description": "Find files matching a glob pattern in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g., '**/*.py', 'src/**/*.ts')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in. Defaults to workspace root.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search file contents using a regex pattern. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search in. Defaults to workspace root.",
                    },
                    "include": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g., '*.py')",
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "Case insensitive search. Default false.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_execute",
            "description": "Execute a shell command in the workspace directory. Use for running programs, git commands, package management, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default 120.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory. Defaults to workspace root.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the project's test suite or specific tests. Detects the test framework and runs appropriately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_path": {
                        "type": "string",
                        "description": "Specific test file or directory to run. If empty, runs all tests.",
                    },
                    "framework": {
                        "type": "string",
                        "enum": ["pytest", "jest", "mocha", "go", "cargo", "auto"],
                        "description": "Test framework to use. 'auto' detects from project files. Default 'auto'.",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Run with verbose output. Default false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list. Defaults to workspace root.",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively (max depth 3). Default false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_approval",
            "description": "Ask the user a question and wait for their response. Use this when you need clarification or confirmation before proceeding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of choices to present to the user",
                    },
                },
                "required": ["question"],
            },
        },
    },
]
