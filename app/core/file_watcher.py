import asyncio
from pathlib import Path
from watchfiles import awatch, Change
from app.core.config import settings


class FileWatcher:
    def __init__(self):
        self.changes: list[dict] = []
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        if not settings.watch_enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._watch())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_recent_changes(self, clear: bool = True) -> list[dict]:
        changes = self.changes.copy()
        if clear:
            self.changes.clear()
        return changes

    def get_change_summary(self) -> str:
        changes = self.get_recent_changes()
        if not changes:
            return ""

        summary_parts = []
        for change in changes[-20:]:  # Last 20 changes
            action = change["action"]
            path = change["path"]
            summary_parts.append(f"  {action}: {path}")

        return "Recent file changes:\n" + "\n".join(summary_parts)

    async def _watch(self):
        watch_path = Path(settings.workspace_dir)
        if not watch_path.exists():
            return

        try:
            async for changes in awatch(
                watch_path,
                watch_filter=self._filter,
                stop_event=asyncio.Event() if not self._running else None,
            ):
                if not self._running:
                    break
                for change_type, path in changes:
                    rel_path = str(Path(path).relative_to(watch_path))
                    action = {
                        Change.added: "added",
                        Change.modified: "modified",
                        Change.deleted: "deleted",
                    }.get(change_type, "unknown")

                    self.changes.append({"action": action, "path": rel_path})

                    # Keep only last 100 changes
                    if len(self.changes) > 100:
                        self.changes = self.changes[-100:]
        except asyncio.CancelledError:
            pass

    def _filter(self, change: Change, path: str) -> bool:
        path_str = str(path)
        for pattern in settings.watch_ignore_patterns:
            # Simple pattern matching for common ignores
            clean_pattern = pattern.replace("**/", "").replace("/**", "")
            if clean_pattern in path_str:
                return False
        return True


file_watcher = FileWatcher()
