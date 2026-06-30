import os
import shutil
import fnmatch
import re
from pathlib import Path
from app.core.config import settings


def resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(settings.workspace_dir, path)


def file_read(path: str, offset: int = 0, limit: int | None = None) -> str:
    resolved = resolve_path(path)
    if not os.path.exists(resolved):
        return f"Error: File not found: {resolved}"
    if not os.path.isfile(resolved):
        return f"Error: Not a file: {resolved}"

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if offset > 0:
            lines = lines[offset:]
        if limit is not None:
            lines = lines[:limit]

        numbered = []
        for i, line in enumerate(lines, start=offset + 1):
            numbered.append(f"{i}\t{line.rstrip()}")

        return "\n".join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


def file_write(path: str, content: str) -> str:
    resolved = resolve_path(path)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def file_edit(path: str, old_string: str, new_string: str) -> str:
    resolved = resolve_path(path)
    if not os.path.exists(resolved):
        return f"Error: File not found: {resolved}"

    try:
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return "Error: old_string not found in file"
        if count > 1:
            return f"Error: old_string found {count} times. Provide more context to make it unique."

        new_content = content.replace(old_string, new_string, 1)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"Successfully edited {path}"
    except Exception as e:
        return f"Error editing file: {e}"


def file_delete(path: str, recursive: bool = False) -> str:
    resolved = resolve_path(path)
    if not os.path.exists(resolved):
        return f"Error: Path not found: {resolved}"

    try:
        if os.path.isdir(resolved):
            if recursive:
                shutil.rmtree(resolved)
            else:
                os.rmdir(resolved)
        else:
            os.remove(resolved)
        return f"Successfully deleted {path}"
    except Exception as e:
        return f"Error deleting: {e}"


def glob_search(pattern: str, path: str | None = None) -> str:
    base = resolve_path(path) if path else settings.workspace_dir
    if not os.path.isdir(base):
        return f"Error: Directory not found: {base}"

    matches = []
    for root, dirs, files in os.walk(base):
        # Skip hidden and common ignore dirs
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv")
        ]

        for name in files + dirs:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, base)
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(name, pattern):
                matches.append(rel_path)

        if len(matches) > 500:
            matches.append("... (truncated at 500 results)")
            break

    if not matches:
        return f"No files matching pattern: {pattern}"
    return "\n".join(sorted(matches))


def grep_search(
    pattern: str, path: str | None = None, include: str | None = None, ignore_case: bool = False
) -> str:
    base = resolve_path(path) if path else settings.workspace_dir

    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex: {e}"

    results = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv")
        ]

        for name in files:
            if include and not fnmatch.fnmatch(name, include):
                continue

            file_path = os.path.join(root, name)
            rel_path = os.path.relpath(file_path, settings.workspace_dir)

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{rel_path}:{line_num}: {line.rstrip()}")
                            if len(results) > 200:
                                break
            except (OSError, UnicodeDecodeError):
                continue

            if len(results) > 200:
                results.append("... (truncated at 200 results)")
                break

        if len(results) > 200:
            break

    if not results:
        return f"No matches for pattern: {pattern}"
    return "\n".join(results)


def list_directory(path: str | None = None, recursive: bool = False) -> str:
    base = resolve_path(path) if path else settings.workspace_dir
    if not os.path.isdir(base):
        return f"Error: Directory not found: {base}"

    entries = []

    if not recursive:
        for entry in sorted(os.listdir(base)):
            full = os.path.join(base, entry)
            prefix = "d " if os.path.isdir(full) else "f "
            entries.append(f"{prefix}{entry}")
    else:
        for root, dirs, files in os.walk(base):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv")
            ]
            depth = root.replace(base, "").count(os.sep)
            if depth >= 3:
                dirs.clear()
                continue

            rel = os.path.relpath(root, base)
            if rel != ".":
                entries.append(f"d {rel}/")
            for f in sorted(files):
                entries.append(f"f {os.path.join(rel, f) if rel != '.' else f}")

    if not entries:
        return "Directory is empty"
    return "\n".join(entries[:500])
