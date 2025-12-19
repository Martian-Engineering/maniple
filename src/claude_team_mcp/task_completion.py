"""
Task Completion Detection

Detects when a delegated task is truly complete using multiple strategies.

PRIMARY METHOD:
- Stop hook detection (0.99 confidence) - Authoritative signal from Claude Code
  itself via the Stop hook system. This is the recommended approach.

FALLBACK METHODS (legacy, lower confidence):
- Convention-based markers in conversation (0.75-0.95) - DEPRECATED as primary
- Git commit detection (0.7) - Suggests progress but not certainty
- Beads issue status monitoring (0.6-0.9) - Useful when issues are linked
- Screen parsing for completion patterns (0.6) - Last resort
- Idle detection (0.5) - DEPRECATED, unreliable
"""

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .session_state import Message, SessionState, parse_session, is_session_stopped

logger = logging.getLogger("claude-team-mcp")


class TaskStatus(str, Enum):
    """Status of a delegated task."""

    PENDING = "pending"  # Task sent but no activity yet
    IN_PROGRESS = "in_progress"  # Task is being worked on
    COMPLETED = "completed"  # Task finished successfully
    FAILED = "failed"  # Task failed
    UNKNOWN = "unknown"  # Cannot determine status


@dataclass
class TaskCompletionInfo:
    """
    Information about task completion status.

    Contains the detected status, evidence for the detection,
    and any relevant details like git commits or beads issues closed.
    """

    status: TaskStatus
    confidence: float  # 0.0 to 1.0
    detection_method: str  # Which method detected completion
    details: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP tool responses."""
        return {
            "status": self.status.value,
            "confidence": self.confidence,
            "detection_method": self.detection_method,
            "details": self.details,
            "detected_at": self.detected_at.isoformat(),
        }


# =============================================================================
# Convention-Based Detection (DEPRECATED as primary method)
# =============================================================================
# NOTE: These markers and patterns are now FALLBACK methods only.
# The Stop hook system (detect_stop_hook_completion) is the primary detection
# method with 0.99 confidence. Convention markers remain available for:
# - Sessions without Stop hook injection
# - Edge cases where Stop hook doesn't fire
# - Backwards compatibility
# =============================================================================

# Markers that indicate task completion (fallback detection)
COMPLETION_MARKERS = [
    "TASK_COMPLETE",
    "TASK_COMPLETED",
    "[COMPLETE]",
    "[COMPLETED]",
    "✓ TASK COMPLETE",
    "✅ TASK COMPLETE",
]

# Markers that indicate task failure (fallback detection)
FAILURE_MARKERS = [
    "TASK_FAILED",
    "TASK_FAILURE",
    "[FAILED]",
    "[FAILURE]",
    "✗ TASK FAILED",
    "❌ TASK FAILED",
]

# Natural language patterns suggesting completion (fallback, 0.75 confidence)
COMPLETION_PATTERNS = [
    r"(?i)(?:I've|I have) (?:completed|finished|done|implemented) (?:the |all |)(?:task|work|changes)",
    r"(?i)(?:task|work) (?:is |has been )(?:complete|completed|finished|done)",
    r"(?i)all (?:requested |)(?:changes|tasks|work) (?:have been |are )(?:complete|completed|done)",
    r"(?i)(?:everything|all) (?:is |has been )(?:complete|completed|done|implemented)",
    r"(?i)successfully (?:completed|finished|implemented)",
    r"(?i)the (?:feature|fix|change|implementation) is (?:complete|ready|done)",
]

# Patterns suggesting failure (fallback, 0.75 confidence)
FAILURE_PATTERNS = [
    r"(?i)(?:I |we )(?:cannot|can't|couldn't) (?:complete|finish|implement)",
    r"(?i)(?:task|work) (?:failed|blocked|cannot be completed)",
    r"(?i)(?:error|failure|exception) (?:occurred|happened|prevented)",
    r"(?i)unable to (?:complete|finish|proceed)",
]


def detect_markers_in_message(content: str) -> tuple[TaskStatus, float, str]:
    """
    Check a message for convention-based completion/failure markers.

    Args:
        content: Message content to analyze

    Returns:
        Tuple of (status, confidence, matched_marker)
    """
    # Check explicit markers first (high confidence)
    for marker in COMPLETION_MARKERS:
        if marker in content:
            return TaskStatus.COMPLETED, 0.95, marker

    for marker in FAILURE_MARKERS:
        if marker in content:
            return TaskStatus.FAILED, 0.95, marker

    # Check natural language patterns (medium confidence)
    for pattern in COMPLETION_PATTERNS:
        if re.search(pattern, content):
            return TaskStatus.COMPLETED, 0.75, pattern

    for pattern in FAILURE_PATTERNS:
        if re.search(pattern, content):
            return TaskStatus.FAILED, 0.75, pattern

    return TaskStatus.UNKNOWN, 0.0, ""


def detect_from_conversation(
    state: SessionState, since_message_uuid: Optional[str] = None
) -> Optional[TaskCompletionInfo]:
    """
    Analyze conversation for completion markers.

    Args:
        state: Parsed session state
        since_message_uuid: Only analyze messages after this UUID

    Returns:
        TaskCompletionInfo if completion detected, None otherwise
    """
    # Filter to messages after the baseline
    messages = state.messages
    if since_message_uuid:
        found_baseline = False
        filtered = []
        for msg in messages:
            if found_baseline:
                filtered.append(msg)
            elif msg.uuid == since_message_uuid:
                found_baseline = True
        messages = filtered

    # Analyze assistant messages for markers
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.content:
            status, confidence, marker = detect_markers_in_message(msg.content)
            if status != TaskStatus.UNKNOWN:
                return TaskCompletionInfo(
                    status=status,
                    confidence=confidence,
                    detection_method="convention_markers",
                    details={
                        "matched_marker": marker,
                        "message_uuid": msg.uuid,
                        "message_preview": msg.content[:200],
                    },
                )

    return None


# =============================================================================
# Git Commit Detection
# =============================================================================


def detect_git_commits(
    project_path: str, since_timestamp: Optional[datetime] = None
) -> Optional[TaskCompletionInfo]:
    """
    Check if new commits have been made in the project.

    Args:
        project_path: Path to the git repository
        since_timestamp: Only count commits after this time

    Returns:
        TaskCompletionInfo if commits detected, None otherwise
    """
    try:
        # Build git log command
        cmd = ["git", "log", "--oneline", "-n", "10"]
        if since_timestamp:
            # Format timestamp for git
            since_str = since_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            cmd.extend(["--since", since_str])

        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return None

        commits = result.stdout.strip().split("\n")
        commits = [c for c in commits if c.strip()]

        if commits:
            # Get current branch
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            current_branch = branch_result.stdout.strip()

            return TaskCompletionInfo(
                status=TaskStatus.COMPLETED,
                confidence=0.7,  # Git commits suggest progress, not certainty
                detection_method="git_commits",
                details={
                    "commit_count": len(commits),
                    "commits": commits[:5],  # First 5 commits
                    "branch": current_branch,
                },
            )

    except subprocess.TimeoutExpired:
        logger.warning(f"Git command timed out for {project_path}")
    except Exception as e:
        logger.warning(f"Git detection failed for {project_path}: {e}")

    return None


# =============================================================================
# Beads Issue Detection
# =============================================================================


def detect_beads_completion(
    project_path: str, issue_id: Optional[str] = None
) -> Optional[TaskCompletionInfo]:
    """
    Check beads issue status for completion signals.

    Args:
        project_path: Path to the project (for bd command context)
        issue_id: Specific issue ID to check, or None to check recent closures

    Returns:
        TaskCompletionInfo if issue closed, None otherwise
    """
    try:
        if issue_id:
            # Check specific issue
            result = subprocess.run(
                ["bd", "--no-db", "show", issue_id],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "NO_COLOR": "1"},
            )

            if result.returncode != 0:
                return None

            output = result.stdout
            if "Status: closed" in output or "Status: done" in output:
                return TaskCompletionInfo(
                    status=TaskStatus.COMPLETED,
                    confidence=0.9,
                    detection_method="beads_issue",
                    details={
                        "issue_id": issue_id,
                        "status": "closed",
                    },
                )
            elif "Status: in_progress" in output:
                return TaskCompletionInfo(
                    status=TaskStatus.IN_PROGRESS,
                    confidence=0.8,
                    detection_method="beads_issue",
                    details={
                        "issue_id": issue_id,
                        "status": "in_progress",
                    },
                )
        else:
            # Check for any recently closed issues
            result = subprocess.run(
                ["bd", "--no-db", "list", "--status", "closed"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "NO_COLOR": "1"},
            )

            if result.returncode == 0 and result.stdout.strip():
                # Parse recently closed issues
                lines = result.stdout.strip().split("\n")
                if lines:
                    return TaskCompletionInfo(
                        status=TaskStatus.COMPLETED,
                        confidence=0.6,  # Lower confidence without specific issue
                        detection_method="beads_issue",
                        details={
                            "closed_count": len(lines),
                            "issues": lines[:5],
                        },
                    )

    except subprocess.TimeoutExpired:
        logger.warning(f"Beads command timed out for {project_path}")
    except Exception as e:
        logger.warning(f"Beads detection failed for {project_path}: {e}")

    return None


# =============================================================================
# Screen Content Detection
# =============================================================================

# Patterns in terminal output suggesting completion
SCREEN_COMPLETION_PATTERNS = [
    r"(?i)done!?$",
    r"(?i)complete!?$",
    r"(?i)finished!?$",
    r"(?i)all (?:tests? )?pass(?:ed|ing)?",
    r"(?i)build succeeded",
    r"(?i)successfully",
    r"✓",
    r"✅",
]

# Patterns suggesting errors/failures
SCREEN_FAILURE_PATTERNS = [
    r"(?i)error:",
    r"(?i)failed:",
    r"(?i)exception:",
    r"(?i)tests? failed",
    r"(?i)build failed",
    r"✗",
    r"❌",
]


async def detect_from_screen(
    iterm_session, read_screen_func
) -> Optional[TaskCompletionInfo]:
    """
    Analyze terminal screen content for completion signals.

    Checks for explicit convention markers (TASK_COMPLETE, TASK_FAILED) first
    with high confidence, then falls back to generic patterns with lower
    confidence.

    Args:
        iterm_session: iTerm2 session object
        read_screen_func: Function to read screen text

    Returns:
        TaskCompletionInfo if completion detected, None otherwise
    """
    try:
        screen_text = await read_screen_func(iterm_session)

        # Check last few lines for completion/failure patterns
        lines = [l.strip() for l in screen_text.split("\n") if l.strip()]
        recent_text = "\n".join(lines[-20:])  # Last 20 non-empty lines

        # Check for explicit convention markers FIRST (highest priority, high confidence)
        # These are the same markers used in conversation detection
        for marker in FAILURE_MARKERS:
            if marker in recent_text:
                return TaskCompletionInfo(
                    status=TaskStatus.FAILED,
                    confidence=0.95,
                    detection_method="screen_convention_marker",
                    details={
                        "matched_marker": marker,
                        "screen_preview": "\n".join(lines[-5:]),
                    },
                )

        for marker in COMPLETION_MARKERS:
            if marker in recent_text:
                return TaskCompletionInfo(
                    status=TaskStatus.COMPLETED,
                    confidence=0.95,
                    detection_method="screen_convention_marker",
                    details={
                        "matched_marker": marker,
                        "screen_preview": "\n".join(lines[-5:]),
                    },
                )

        # Fall back to generic failure patterns (lower confidence)
        for pattern in SCREEN_FAILURE_PATTERNS:
            if re.search(pattern, recent_text):
                return TaskCompletionInfo(
                    status=TaskStatus.FAILED,
                    confidence=0.6,
                    detection_method="screen_parsing",
                    details={
                        "matched_pattern": pattern,
                        "screen_preview": "\n".join(lines[-5:]),
                    },
                )

        # Fall back to generic completion patterns (lower confidence)
        for pattern in SCREEN_COMPLETION_PATTERNS:
            if re.search(pattern, recent_text):
                return TaskCompletionInfo(
                    status=TaskStatus.COMPLETED,
                    confidence=0.6,
                    detection_method="screen_parsing",
                    details={
                        "matched_pattern": pattern,
                        "screen_preview": "\n".join(lines[-5:]),
                    },
                )

    except Exception as e:
        logger.warning(f"Screen detection failed: {e}")

    return None


# =============================================================================
# Idle Detection (DEPRECATED - low reliability)
# =============================================================================
# NOTE: Idle detection is DEPRECATED as a completion signal. It only checks
# file modification time which is unreliable - Claude may be "thinking" or
# waiting for user input. The Stop hook system is the authoritative method.
#
# This function remains available as a last-resort fallback with very low
# confidence (0.5), but should not be relied upon for task completion.
# =============================================================================


def detect_idle_completion(
    state: SessionState, idle_seconds: float = 30.0
) -> Optional[TaskCompletionInfo]:
    """
    DEPRECATED: Check if the session has been idle (suggesting completion).

    WARNING: This method is deprecated and unreliable. It only checks JSONL
    file mtime which doesn't distinguish between "Claude is done" and "Claude
    is thinking" or "waiting for input". Use Stop hook detection instead.

    Retained as a low-confidence (0.5) fallback for edge cases where Stop
    hook data is unavailable.

    Args:
        state: Parsed session state
        idle_seconds: Seconds of inactivity to consider "complete"

    Returns:
        TaskCompletionInfo if idle detected, None otherwise
    """
    if not state.messages:
        return None

    # Check if not processing (no pending tool use)
    if state.is_processing:
        return TaskCompletionInfo(
            status=TaskStatus.IN_PROGRESS,
            confidence=0.9,
            detection_method="idle_detection",
            details={"is_processing": True},
        )

    # Check file modification time
    import time

    if state.jsonl_path.exists():
        mtime = state.jsonl_path.stat().st_mtime
        idle_time = time.time() - mtime

        if idle_time >= idle_seconds:
            last_msg = state.last_assistant_message
            return TaskCompletionInfo(
                status=TaskStatus.COMPLETED,
                confidence=0.5,  # Low confidence - just idle, not confirmed complete
                detection_method="idle_detection",
                details={
                    "idle_seconds": idle_time,
                    "last_message_preview": (
                        last_msg.content[:200] if last_msg else None
                    ),
                },
            )

    return None


# =============================================================================
# Stop Hook Detection (Primary Method)
# =============================================================================


def detect_stop_hook_completion(
    jsonl_path: Path,
    session_id: str,
) -> Optional[TaskCompletionInfo]:
    """
    Detect completion via Stop hook marker in JSONL.

    This is the primary detection method. When workers are spawned with
    Stop hook injection, their completion is reliably signaled via a marker
    embedded in the hook command that gets logged to the JSONL.

    The detection checks:
    1. A stop_hook_summary exists with the session's marker
    2. No user/assistant messages exist after that stop_hook_summary

    Args:
        jsonl_path: Path to the session JSONL file
        session_id: The session ID to check (matches marker in Stop hook)

    Returns:
        TaskCompletionInfo if stopped, None if still working or no hook data
    """
    if not jsonl_path.exists():
        return None

    if is_session_stopped(jsonl_path, session_id):
        return TaskCompletionInfo(
            status=TaskStatus.COMPLETED,
            confidence=0.99,  # Authoritative signal from Claude Code itself
            detection_method="stop_hook",
            details={
                "session_id": session_id,
                "signal": "stop_hook_summary detected with no subsequent messages",
            },
        )

    return None


# =============================================================================
# Combined Detection
# =============================================================================


@dataclass
class TaskContext:
    """
    Context for tracking a delegated task.

    Stores the baseline state when a task was delegated,
    allowing detection methods to compare against it.
    """

    session_id: str
    project_path: str
    started_at: datetime
    baseline_message_uuid: Optional[str] = None  # Last message UUID when task sent
    beads_issue_id: Optional[str] = None  # Optional linked beads issue
    task_description: Optional[str] = None  # The task that was delegated


async def detect_task_completion(
    task_ctx: TaskContext,
    session_state: Optional[SessionState] = None,
    iterm_session=None,
    read_screen_func=None,
    check_git: bool = True,
    check_beads: bool = True,
    check_screen: bool = True,
    check_stop_hook: bool = True,
    idle_threshold: float = 30.0,
    jsonl_path: Optional[Path] = None,
) -> TaskCompletionInfo:
    """
    Run all detection methods and return the best result.

    Combines multiple detection strategies and returns the result
    with the highest confidence.

    Detection priority (highest to lowest):
    1. Stop hook (0.99) - PRIMARY METHOD, authoritative signal from Claude Code
    2. Beads issues (0.9) - Issue closed (useful when linked)
    3. Convention markers (0.75-0.95) - FALLBACK, explicit TASK_COMPLETE markers
    4. Natural language (0.75) - FALLBACK, completion phrases in conversation
    5. Git commits (0.7) - Suggests progress but not certainty
    6. Screen patterns (0.6) - Last resort pattern matching
    7. Idle (0.5) - DEPRECATED, unreliable file mtime check

    NOTE: Stop hook detection is the recommended primary method. If Stop hook
    returns a result, it short-circuits and returns immediately. Other methods
    are fallbacks for sessions without Stop hook injection or edge cases.

    Args:
        task_ctx: Context about the delegated task
        session_state: Parsed JSONL state (optional)
        iterm_session: iTerm2 session for screen reading (optional)
        read_screen_func: Function to read screen text (optional)
        check_git: Whether to check for git commits
        check_beads: Whether to check beads issues
        check_screen: Whether to parse screen content
        check_stop_hook: Whether to check Stop hook markers (recommended)
        idle_threshold: Seconds to consider idle as complete
        jsonl_path: Path to JSONL file for Stop hook detection

    Returns:
        TaskCompletionInfo with the best detected status
    """
    results: list[TaskCompletionInfo] = []

    # 0. Stop hook detection (highest priority, authoritative signal)
    # This is the primary detection method when workers have Stop hook injection
    if check_stop_hook and jsonl_path:
        stop_hook_result = detect_stop_hook_completion(
            jsonl_path, task_ctx.session_id
        )
        if stop_hook_result:
            # Stop hook is authoritative - return immediately
            return stop_hook_result

    # 1. Convention markers in conversation (fallback method)
    if session_state:
        conv_result = detect_from_conversation(
            session_state, task_ctx.baseline_message_uuid
        )
        if conv_result:
            results.append(conv_result)

        # 2. Idle detection (DEPRECATED - low confidence fallback)
        idle_result = detect_idle_completion(session_state, idle_threshold)
        if idle_result:
            results.append(idle_result)

    # 3. Git commit detection
    if check_git:
        git_result = detect_git_commits(task_ctx.project_path, task_ctx.started_at)
        if git_result:
            results.append(git_result)

    # 4. Beads issue detection
    if check_beads:
        beads_result = detect_beads_completion(
            task_ctx.project_path, task_ctx.beads_issue_id
        )
        if beads_result:
            results.append(beads_result)

    # 5. Screen parsing
    if check_screen and iterm_session and read_screen_func:
        screen_result = await detect_from_screen(iterm_session, read_screen_func)
        if screen_result:
            results.append(screen_result)

    # Return highest confidence result
    if results:
        # Sort by confidence (descending), then by status priority
        status_priority = {
            TaskStatus.COMPLETED: 1,
            TaskStatus.FAILED: 2,
            TaskStatus.IN_PROGRESS: 3,
            TaskStatus.PENDING: 4,
            TaskStatus.UNKNOWN: 5,
        }
        results.sort(
            key=lambda r: (-r.confidence, status_priority.get(r.status, 5))
        )
        return results[0]

    # Default: unknown
    return TaskCompletionInfo(
        status=TaskStatus.UNKNOWN,
        confidence=0.0,
        detection_method="none",
        details={"checked_methods": ["conversation", "git", "beads", "screen"]},
    )


async def wait_for_task_completion(
    task_ctx: TaskContext,
    jsonl_path: Path,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
    idle_threshold: float = 30.0,
    iterm_session=None,
    read_screen_func=None,
) -> TaskCompletionInfo:
    """
    Wait for a delegated task to complete.

    Polls the session state and other signals until completion
    is detected or timeout is reached.

    Args:
        task_ctx: Context about the delegated task
        jsonl_path: Path to session JSONL file
        timeout: Maximum seconds to wait
        poll_interval: Seconds between checks
        idle_threshold: Seconds of inactivity to consider complete
        iterm_session: iTerm2 session for screen reading
        read_screen_func: Function to read screen text

    Returns:
        TaskCompletionInfo with final status
    """
    import time

    start = time.time()
    last_check = None

    while time.time() - start < timeout:
        # Parse current state
        session_state = None
        if jsonl_path.exists():
            session_state = parse_session(jsonl_path)

        # Run detection
        result = await detect_task_completion(
            task_ctx=task_ctx,
            session_state=session_state,
            iterm_session=iterm_session,
            read_screen_func=read_screen_func,
            idle_threshold=idle_threshold,
            jsonl_path=jsonl_path,
        )

        # Return if completed or failed with good confidence
        if result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            if result.confidence >= 0.7:
                return result

        # Store last check for timeout result
        last_check = result

        await asyncio.sleep(poll_interval)

    # Timeout - return last result or unknown
    if last_check:
        last_check.details["timeout"] = True
        last_check.details["waited_seconds"] = timeout
        return last_check

    return TaskCompletionInfo(
        status=TaskStatus.UNKNOWN,
        confidence=0.0,
        detection_method="timeout",
        details={"timeout": True, "waited_seconds": timeout},
    )
