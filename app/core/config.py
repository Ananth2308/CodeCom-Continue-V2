from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_api_key: str = "EMPTY"
    vllm_model: str = "default"

    proxy_host: str = "0.0.0.0"
    proxy_port: int = 8080

    workspace_dir: str = "/home/ubuntu/workspace"

    # Tools that require human approval before execution
    dangerous_tools: list[str] = [
        "shell_execute",
        "file_write",
        "file_edit",
        "file_delete",
        "run_tests",
    ]

    # Whether to require approval for dangerous tools
    require_approval: bool = True

    # Max iterations for the agent loop to prevent runaway
    max_agent_iterations: int = 50

    # File watcher
    watch_enabled: bool = True
    watch_ignore_patterns: list[str] = [
        "**/.git/**",
        "**/node_modules/**",
        "**/__pycache__/**",
        "**/.venv/**",
    ]

    class Config:
        env_file = ".env"
        env_prefix = "AGENT_"


settings = Settings()
