#!/usr/bin/env python3
"""
Agents IDE - Action History

SQLite-based history tracking for all file modifications.
Uses git unified diffs for efficient storage.
Supports reverting changes via git apply --reverse.
"""

import json
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _compute_diff(before: str, after: str, file_path: str) -> str:
    """Compute a unified diff between before and after content using git."""
    if not before and not after:
        return ""
    if before == after:
        return ""

    # Normalize file_path to be relative or just filename for cleaner diffs
    file_name = Path(file_path).name

    with tempfile.TemporaryDirectory() as tmpdir:
        before_file = Path(tmpdir) / "before"
        after_file = Path(tmpdir) / "after"

        before_file.write_text(before or "")
        after_file.write_text(after or "")

        # Use git diff with unified format
        result = subprocess.run(
            ["git", "diff", "--no-index", "-u", "--no-color",
             f"--src-prefix=a/", f"--dst-prefix=b/",
             str(before_file), str(after_file)],
            capture_output=True,
            text=True
        )
        # git diff returns 1 when there are differences, 0 when none
        diff = result.stdout or ""

        # Replace temp file names with actual file path in the diff
        if diff:
            # Replace the full temp paths
            diff = diff.replace(str(before_file), file_name)
            diff = diff.replace(str(after_file), file_name)
            # Clean up the header to use the actual file path
            lines = diff.split('\n')
            new_lines = []
            for line in lines:
                if line.startswith('diff --git'):
                    line = f'diff --git a/{file_name} b/{file_name}'
                elif line.startswith('--- a/'):
                    line = f'--- a/{file_name}'
                elif line.startswith('+++ b/'):
                    line = f'+++ b/{file_name}'
                new_lines.append(line)
            diff = '\n'.join(new_lines)

        return diff


def _apply_diff(file_path: str, diff: str, reverse: bool = False) -> bool:
    """Apply a diff to a file. Returns True on success."""
    if not diff:
        return False

    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
        f.write(diff)
        patch_file = f.name

    try:
        cmd = ["git", "apply", "--verbose"]
        if reverse:
            cmd.append("--reverse")
        cmd.append(patch_file)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path(file_path).parent)
        )
        return result.returncode == 0
    finally:
        Path(patch_file).unlink(missing_ok=True)


@dataclass
class HistoryEntry:
    """A single history entry."""
    id: int
    timestamp: float
    action: str
    file_path: str
    diff: Optional[str]            # Git unified diff
    before_content: Optional[str]  # Original content for fallback revert
    after_content: Optional[str]   # Content after change for verification
    metadata: dict
    reverted: bool = False


class ActionHistory:
    """SQLite-based action history with revert capability.

    Uses git unified diffs for storage efficiency. Stores:
    - diff: The unified diff (forward direction)
    - before_content: Original content (for fallback revert)
    """

    def __init__(self, db_path: str = "/tmp/agents_ide_history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            # Create new table with diff column
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    diff TEXT,
                    before_content TEXT,
                    after_content TEXT,
                    metadata TEXT,
                    reverted INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_timestamp
                ON history(timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_file_path
                ON history(file_path)
            """)
            conn.commit()

    def record(
        self,
        action: str,
        file_path: str,
        before_content: Optional[str] = None,
        after_content: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> int:
        """
        Record an action in history using git diff.

        Args:
            action: Type of action (e.g., "edit", "rename", "refactor")
            file_path: Path to the affected file
            before_content: File content before the action
            after_content: File content after the action
            metadata: Additional metadata (operation details, etc.)

        Returns:
            History entry ID
        """
        # Compute unified diff for efficient storage
        diff = _compute_diff(before_content or "", after_content or "", file_path)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO history (timestamp, action, file_path, diff, before_content, after_content, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    action,
                    file_path,
                    diff,
                    before_content,  # Keep for fallback
                    after_content,   # Keep for verification
                    json.dumps(metadata or {})
                )
            )
            conn.commit()
            return cursor.lastrowid

    def get_entry(self, entry_id: int) -> Optional[HistoryEntry]:
        """Get a specific history entry by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM history WHERE id = ?",
                (entry_id,)
            ).fetchone()

            if row:
                return HistoryEntry(
                    id=row["id"],
                    timestamp=row["timestamp"],
                    action=row["action"],
                    file_path=row["file_path"],
                    diff=row["diff"] if "diff" in row.keys() else None,
                    before_content=row["before_content"],
                    after_content=row["after_content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    reverted=bool(row["reverted"])
                )
            return None

    def get_recent(self, limit: int = 50, file_path: Optional[str] = None) -> list[HistoryEntry]:
        """
        Get recent history entries.

        Args:
            limit: Maximum number of entries to return
            file_path: Optional filter by file path
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if file_path:
                rows = conn.execute(
                    """
                    SELECT * FROM history
                    WHERE file_path = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (file_path, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM history
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,)
                ).fetchall()

            return [
                HistoryEntry(
                    id=row["id"],
                    timestamp=row["timestamp"],
                    action=row["action"],
                    file_path=row["file_path"],
                    diff=row["diff"] if "diff" in row.keys() else None,
                    before_content=row["before_content"],
                    after_content=row["after_content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    reverted=bool(row["reverted"])
                )
                for row in rows
            ]

    def can_revert(self, entry_id: int) -> dict:
        """
        Check if an entry can be reverted (no conflicts).

        Uses git apply --check to test if the reverse patch applies cleanly.
        A file can change in other parts and still be revertable.

        Returns dict with 'can_revert' bool and 'reason' if not.
        """
        entry = self.get_entry(entry_id)
        if not entry:
            return {"can_revert": False, "reason": f"Entry {entry_id} not found"}
        if entry.reverted:
            return {"can_revert": False, "reason": "Already reverted"}
        if not entry.diff and not entry.before_content:
            return {"can_revert": False, "reason": "No diff or content to restore"}

        file_path = Path(entry.file_path)

        # If we have a diff, test if it applies cleanly
        if entry.diff:
            # Use git apply --check --reverse to test without actually applying
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(entry.diff)
                patch_file = f.name
            try:
                result = subprocess.run(
                    ["git", "apply", "--check", "--reverse", patch_file],
                    capture_output=True,
                    text=True,
                    cwd=str(file_path.parent) if file_path.parent.exists() else "."
                )
                if result.returncode == 0:
                    return {"can_revert": True, "method": "git_apply"}
                else:
                    # Git apply would fail - check why
                    return {
                        "can_revert": False,
                        "reason": "Patch doesn't apply cleanly (conflict in changed lines)",
                        "git_error": result.stderr.strip(),
                        "hint": "The specific lines changed by this action were modified. Manual merge may be needed."
                    }
            finally:
                Path(patch_file).unlink(missing_ok=True)

        # Fallback: check if before_content can be restored directly
        if entry.before_content:
            if file_path.exists():
                current = file_path.read_text()
                if entry.after_content and current != entry.after_content:
                    return {
                        "can_revert": True,
                        "method": "direct_restore",
                        "warning": "File was modified; will restore to original state (overwrites all changes)"
                    }
            return {"can_revert": True, "method": "direct_restore"}

        return {"can_revert": False, "reason": "No revert method available"}

    def revert(self, entry_id: int, force: bool = False) -> dict:
        """
        Revert a specific action using git apply --reverse.

        If force=True, will overwrite file with original content even if
        there are conflicts (losing any changes made after the action).

        Args:
            entry_id: ID of the history entry to revert
            force: If True, overwrite with original content even on conflict

        Returns:
            Dict with success status and message
        """
        entry = self.get_entry(entry_id)
        if not entry:
            return {"success": False, "error": f"Entry {entry_id} not found"}

        if entry.reverted:
            return {"success": False, "error": f"Entry {entry_id} already reverted"}

        if not entry.diff and entry.before_content is None:
            return {"success": False, "error": "No diff or before_content to restore"}

        file_path = Path(entry.file_path)
        current_content = file_path.read_text() if file_path.exists() else None

        # Try git apply --reverse first (allows changes in other parts of file)
        reverted_via = None
        git_error = None

        if entry.diff:
            if _apply_diff(str(file_path), entry.diff, reverse=True):
                reverted_via = "git_apply"
            else:
                # Git apply failed - capture error for reporting
                # Try to get the actual error
                with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                    f.write(entry.diff)
                    patch_file = f.name
                try:
                    result = subprocess.run(
                        ["git", "apply", "--reverse", patch_file],
                        capture_output=True, text=True,
                        cwd=str(file_path.parent) if file_path.parent.exists() else "."
                    )
                    git_error = result.stderr.strip()
                finally:
                    Path(patch_file).unlink(missing_ok=True)

        # If git apply failed, handle based on force option
        if not reverted_via:
            if entry.before_content:
                if force:
                    # Force restore - overwrite with original content
                    try:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(entry.before_content)
                        reverted_via = "force_restore"
                    except Exception as e:
                        return {"success": False, "error": f"Force restore failed: {e}"}
                else:
                    # Return info about the conflict
                    return {
                        "success": False,
                        "error": "Patch conflict - cannot auto-revert cleanly",
                        "git_error": git_error,
                        "can_force": True,
                        "hint": "The file changed in conflicting lines. Use 'force' param to overwrite with original content."
                    }
            else:
                return {"success": False, "error": "Git apply failed and no fallback content available"}

        # Mark as reverted
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE history SET reverted = 1 WHERE id = ?",
                (entry_id,)
            )
            conn.commit()

        # Record the revert action itself
        after_content = file_path.read_text() if file_path.exists() else None
        self.record(
            action="revert",
            file_path=entry.file_path,
            before_content=current_content,
            after_content=after_content,
            metadata={
                "reverted_entry_id": entry_id,
                "original_action": entry.action,
                "method": reverted_via
            }
        )

        return {
            "success": True,
            "message": f"Reverted {entry.action} on {entry.file_path}",
            "restored_from": datetime.fromtimestamp(entry.timestamp).isoformat(),
            "method": reverted_via
        }

    def revert_file_to_time(self, file_path: str, target_time: float) -> dict:
        """
        Revert a file to its state at a specific time.

        Args:
            file_path: Path to the file
            target_time: Unix timestamp to revert to

        Returns:
            Dict with success status and details
        """
        # Find the most recent entry before target_time
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM history
                WHERE file_path = ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (file_path, target_time)
            ).fetchone()

        if not row:
            return {"success": False, "error": f"No history found for {file_path} before {target_time}"}

        # Get the content from that point
        content_to_restore = row["before_content"] or row["after_content"]
        if not content_to_restore:
            return {"success": False, "error": "No content available to restore"}

        # Read current content for history
        path = Path(file_path)
        current_content = path.read_text() if path.exists() else None

        # Restore
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content_to_restore)

            self.record(
                action="revert_to_time",
                file_path=file_path,
                before_content=current_content,
                after_content=content_to_restore,
                metadata={"target_time": target_time, "from_entry_id": row["id"]}
            )

            return {
                "success": True,
                "message": f"Reverted {file_path} to state at {datetime.fromtimestamp(target_time).isoformat()}",
                "from_entry_id": row["id"]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_file_history(self, file_path: str) -> list[dict]:
        """Get summarized history for a specific file."""
        entries = self.get_recent(limit=100, file_path=file_path)
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "datetime": datetime.fromtimestamp(e.timestamp).isoformat(),
                "action": e.action,
                "reverted": e.reverted,
                "metadata": e.metadata
            }
            for e in entries
        ]

    def clear_old(self, days: int = 7) -> int:
        """Clear history older than specified days."""
        cutoff = time.time() - (days * 24 * 60 * 60)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM history WHERE timestamp < ?",
                (cutoff,)
            )
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> dict:
        """Get history statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            reverted = conn.execute("SELECT COUNT(*) FROM history WHERE reverted = 1").fetchone()[0]
            by_action = dict(conn.execute(
                "SELECT action, COUNT(*) FROM history GROUP BY action"
            ).fetchall())

            oldest = conn.execute(
                "SELECT MIN(timestamp) FROM history"
            ).fetchone()[0]

            return {
                "total_entries": total,
                "reverted_entries": reverted,
                "by_action": by_action,
                "oldest_entry": datetime.fromtimestamp(oldest).isoformat() if oldest else None,
                "db_path": self.db_path
            }


# Singleton instance
_history: Optional[ActionHistory] = None


def get_history() -> ActionHistory:
    """Get the global history instance."""
    global _history
    if _history is None:
        _history = ActionHistory()
    return _history
