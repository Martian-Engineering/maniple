"""
Git worktree utilities for worker session isolation.

Provides functions to create, remove, and list git worktrees, enabling
each worker session to operate in its own isolated working directory
while sharing the same repository history.

Two worktree strategies are supported:

1. External worktrees (legacy):
   ~/.claude-team/worktrees/{repo-path-hash}/{worker-name}-{timestamp}/
   - Created outside the target repo to avoid polluting it
   - No .gitignore modifications needed

2. Local worktrees (preferred):
   {repo}/.worktrees/{bead-description}/ or {name-uuid-description}/
   - Kept within the repo for easier discovery and cleanup
   - Automatically adds .worktrees to .gitignore
"""

import hashlib
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional


# Base directory for all worktrees (outside any repo)
WORKTREE_BASE_DIR = Path.home() / ".claude-team" / "worktrees"

# Local worktree directory name within repos
LOCAL_WORKTREE_DIR = ".worktrees"


def slugify(text: str) -> str:
    """
    Convert text to a URL/filesystem-friendly slug.

    Converts to lowercase, replaces spaces and special chars with dashes,
    and removes consecutive dashes.

    Args:
        text: The text to slugify

    Returns:
        A lowercase, dash-separated string safe for filenames/URLs

    Example:
        slugify("Add local worktrees support")  # "add-local-worktrees-support"
        slugify("Fix Bug #123")                 # "fix-bug-123"
    """
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and underscores with dashes
    text = re.sub(r"[\s_]+", "-", text)
    # Remove any characters that aren't alphanumeric or dashes
    text = re.sub(r"[^a-z0-9-]", "", text)
    # Collapse multiple dashes
    text = re.sub(r"-+", "-", text)
    # Strip leading/trailing dashes
    text = text.strip("-")
    return text


def ensure_gitignore_entry(repo_path: Path, entry: str) -> bool:
    """
    Ensure an entry exists in the repository's .gitignore file.

    Creates the .gitignore file if it doesn't exist. Adds the entry
    on a new line if not already present.

    Args:
        repo_path: Path to the repository root
        entry: The gitignore entry to add (e.g., ".worktrees")

    Returns:
        True if the entry was added, False if it already existed

    Example:
        ensure_gitignore_entry(Path("/path/to/repo"), ".worktrees")
    """
    gitignore_path = Path(repo_path) / ".gitignore"

    # Check if entry already exists
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        lines = content.splitlines()

        # Check for exact match (with or without trailing slash)
        entry_variants = {entry, entry + "/", entry.rstrip("/")}
        for line in lines:
            stripped = line.strip()
            if stripped in entry_variants:
                return False

        # Entry not found, append it
        # Ensure there's a newline before our entry if file doesn't end with one
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore_path.write_text(content)
        return True
    else:
        # Create new .gitignore with the entry
        gitignore_path.write_text(f"{entry}\n")
        return True


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""

    pass


def get_repo_hash(repo_path: Path) -> str:
    """
    Generate a short hash from a repository path.

    Used to create unique subdirectories for each repo's worktrees.

    Args:
        repo_path: Absolute path to the repository

    Returns:
        8-character hex hash of the repo path
    """
    return hashlib.sha256(str(repo_path).encode()).hexdigest()[:8]


def get_worktree_base_for_repo(repo_path: Path) -> Path:
    """
    Get the base directory for a repo's worktrees.

    Args:
        repo_path: Path to the main repository

    Returns:
        Path to ~/.claude-team/worktrees/{repo-hash}/
    """
    repo_path = Path(repo_path).resolve()
    repo_hash = get_repo_hash(repo_path)
    return WORKTREE_BASE_DIR / repo_hash


def create_worktree(
    repo_path: Path,
    worktree_name: str,
    branch: Optional[str] = None,
    timestamp: Optional[int] = None,
) -> Path:
    """
    Create a git worktree for a worker.

    Creates a new worktree at:
        ~/.claude-team/worktrees/{repo-hash}/{worktree_name}-{timestamp}/

    If a branch is specified and doesn't exist, it will be created from HEAD.
    If no branch is specified, creates a detached HEAD worktree.

    Args:
        repo_path: Path to the main repository
        worktree_name: Name for the worktree (worker name, e.g., "John-abc123")
        branch: Branch to checkout (creates new branch from HEAD if doesn't exist)
        timestamp: Unix timestamp for directory name (defaults to current time)

    Returns:
        Path to the created worktree

    Raises:
        WorktreeError: If the git worktree command fails

    Example:
        path = create_worktree(
            repo_path=Path("/path/to/repo"),
            worktree_name="John-abc123",
            branch="John-abc123"
        )
        # Returns: Path("~/.claude-team/worktrees/a1b2c3d4/John-abc123-1703001234")
    """
    repo_path = Path(repo_path).resolve()

    # Generate worktree path outside the repo
    if timestamp is None:
        timestamp = int(time.time())
    worktree_dir_name = f"{worktree_name}-{timestamp}"
    base_dir = get_worktree_base_for_repo(repo_path)
    worktree_path = base_dir / worktree_dir_name

    # Ensure base directory exists
    base_dir.mkdir(parents=True, exist_ok=True)

    # Check if worktree already exists
    if worktree_path.exists():
        raise WorktreeError(f"Worktree already exists at {worktree_path}")

    # Build the git worktree add command
    cmd = ["git", "-C", str(repo_path), "worktree", "add"]

    if branch:
        # Check if branch exists
        branch_check = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        )

        if branch_check.returncode == 0:
            # Branch exists, check it out
            cmd.extend([str(worktree_path), branch])
        else:
            # Branch doesn't exist, create it with -b
            cmd.extend(["-b", branch, str(worktree_path)])
    else:
        # No branch specified, create detached HEAD
        cmd.extend(["--detach", str(worktree_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise WorktreeError(f"Failed to create worktree: {result.stderr.strip()}")

    return worktree_path


def create_local_worktree(
    repo_path: Path,
    worker_name: str,
    bead_id: Optional[str] = None,
    description: Optional[str] = None,
) -> Path:
    """
    Create a git worktree in the repo's .worktrees/ directory.

    Creates a new worktree at:
        {repo}/.worktrees/{bead_id}-{description}/  (if bead_id provided)
        {repo}/.worktrees/{worker_name}-{uuid}-{description}/  (otherwise)

    The branch name matches the worktree directory name for consistency.
    Automatically adds .worktrees to .gitignore if not present.

    Args:
        repo_path: Path to the main repository
        worker_name: Name of the worker (used in fallback naming)
        bead_id: Optional bead issue ID (e.g., "cic-abc123")
        description: Optional description for the worktree

    Returns:
        Path to the created worktree

    Raises:
        WorktreeError: If the git worktree command fails

    Example:
        # With bead ID
        path = create_local_worktree(
            repo_path=Path("/path/to/repo"),
            worker_name="Groucho",
            bead_id="cic-abc",
            description="Add local worktrees"
        )
        # Returns: Path("/path/to/repo/.worktrees/cic-abc-add-local-worktrees")

        # Without bead ID
        path = create_local_worktree(
            repo_path=Path("/path/to/repo"),
            worker_name="Groucho",
            description="Fix bug"
        )
        # Returns: Path("/path/to/repo/.worktrees/groucho-a1b2c3d4-fix-bug")
    """
    repo_path = Path(repo_path).resolve()

    # Build the worktree directory name
    if bead_id:
        # Bead-based naming: {bead_id}-{description}
        if description:
            dir_name = f"{bead_id}-{slugify(description)}"
        else:
            dir_name = bead_id
    else:
        # Fallback naming: {worker_name}-{uuid}-{description}
        short_uuid = uuid.uuid4().hex[:8]
        name_slug = slugify(worker_name)
        if description:
            dir_name = f"{name_slug}-{short_uuid}-{slugify(description)}"
        else:
            dir_name = f"{name_slug}-{short_uuid}"

    # Worktree path inside the repo
    worktrees_dir = repo_path / LOCAL_WORKTREE_DIR
    worktree_path = worktrees_dir / dir_name

    # Ensure .worktrees is in .gitignore
    ensure_gitignore_entry(repo_path, LOCAL_WORKTREE_DIR)

    # Ensure .worktrees directory exists
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    # Check if worktree already exists
    if worktree_path.exists():
        raise WorktreeError(f"Worktree already exists at {worktree_path}")

    # Branch name matches directory name for clarity
    branch_name = dir_name

    # Build the git worktree add command
    cmd = ["git", "-C", str(repo_path), "worktree", "add"]

    # Check if branch exists
    branch_check = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
    )

    if branch_check.returncode == 0:
        # Branch exists, check it out
        cmd.extend([str(worktree_path), branch_name])
    else:
        # Branch doesn't exist, create it with -b
        cmd.extend(["-b", branch_name, str(worktree_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise WorktreeError(f"Failed to create local worktree: {result.stderr.strip()}")

    return worktree_path


def remove_worktree(
    repo_path: Path,
    worktree_path: Path,
    force: bool = True,
) -> bool:
    """
    Remove a worktree directory (does NOT delete the branch).

    The branch is intentionally kept alive so that commits can be
    cherry-picked before manual cleanup.

    Args:
        repo_path: Path to the main repository
        worktree_path: Full path to the worktree to remove
        force: If True, force removal even with uncommitted changes

    Returns:
        True if worktree was successfully removed

    Raises:
        WorktreeError: If the git worktree remove command fails

    Example:
        success = remove_worktree(
            repo_path=Path("/path/to/repo"),
            worktree_path=Path("~/.claude-team/worktrees/a1b2c3d4/John-abc123-1703001234")
        )
    """
    repo_path = Path(repo_path).resolve()
    worktree_path = Path(worktree_path).resolve()

    cmd = ["git", "-C", str(repo_path), "worktree", "remove"]

    if force:
        cmd.append("--force")

    cmd.append(str(worktree_path))

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Check if worktree doesn't exist (not an error)
        if "is not a working tree" in result.stderr or "No such file" in result.stderr:
            return True
        raise WorktreeError(f"Failed to remove worktree: {result.stderr.strip()}")

    # Also run prune to clean up stale worktree references
    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "prune"],
        capture_output=True,
        text=True,
    )

    return True


def list_git_worktrees(repo_path: Path) -> list[dict]:
    """
    List all worktrees registered with git for a repository.

    Parses the porcelain output of git worktree list to provide
    structured information about each worktree.

    Args:
        repo_path: Path to the repository

    Returns:
        List of dicts, each containing:
            - path: Path to the worktree
            - branch: Branch name (or None if detached HEAD)
            - commit: Current HEAD commit hash
            - bare: True if this is the bare repository entry
            - detached: True if HEAD is detached

    Raises:
        WorktreeError: If the git worktree list command fails

    Example:
        worktrees = list_git_worktrees(Path("/path/to/repo"))
        for wt in worktrees:
            print(f"{wt['path']}: {wt['branch'] or 'detached'}")
    """
    repo_path = Path(repo_path).resolve()

    result = subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise WorktreeError(f"Failed to list worktrees: {result.stderr.strip()}")

    worktrees = []
    current_worktree: dict = {}

    for line in result.stdout.strip().split("\n"):
        if not line:
            # Empty line separates worktree entries
            if current_worktree:
                worktrees.append(current_worktree)
                current_worktree = {}
            continue

        if line.startswith("worktree "):
            current_worktree["path"] = Path(line[9:])
            current_worktree["branch"] = None
            current_worktree["commit"] = None
            current_worktree["bare"] = False
            current_worktree["detached"] = False
        elif line.startswith("HEAD "):
            current_worktree["commit"] = line[5:]
        elif line.startswith("branch "):
            # Branch is in format "refs/heads/branch-name"
            branch_ref = line[7:]
            if branch_ref.startswith("refs/heads/"):
                current_worktree["branch"] = branch_ref[11:]
            else:
                current_worktree["branch"] = branch_ref
        elif line == "bare":
            current_worktree["bare"] = True
        elif line == "detached":
            current_worktree["detached"] = True

    # Don't forget the last entry
    if current_worktree:
        worktrees.append(current_worktree)

    return worktrees


def list_claude_team_worktrees(repo_path: Path) -> list[dict]:
    """
    List all claude-team worktrees for a repository.

    Finds worktrees in ~/.claude-team/worktrees/{repo-hash}/ and
    cross-references them with git's worktree list.

    Args:
        repo_path: Path to the repository

    Returns:
        List of dicts, each containing:
            - path: Path to the worktree directory
            - name: Worktree directory name (e.g., "John-abc123-1703001234")
            - branch: Branch name (if found in git worktree list)
            - commit: Current HEAD commit hash (if found)
            - registered: True if git knows about this worktree
            - exists: True if the directory exists on disk

    Example:
        worktrees = list_claude_team_worktrees(Path("/path/to/repo"))
        for wt in worktrees:
            status = "active" if wt["registered"] else "orphaned"
            print(f"{wt['name']}: {status}")
    """
    repo_path = Path(repo_path).resolve()
    base_dir = get_worktree_base_for_repo(repo_path)

    # Get git's view of worktrees
    try:
        git_worktrees = list_git_worktrees(repo_path)
    except WorktreeError:
        git_worktrees = []

    git_worktree_paths = {str(wt["path"]) for wt in git_worktrees}

    worktrees = []

    # Check if base directory exists
    if not base_dir.exists():
        return worktrees

    # Scan the directory for worktree folders
    for item in base_dir.iterdir():
        if not item.is_dir():
            continue

        wt_path_str = str(item.resolve())
        registered = wt_path_str in git_worktree_paths

        # Find matching git worktree info if registered
        git_info = None
        for gwt in git_worktrees:
            if str(gwt["path"]) == wt_path_str:
                git_info = gwt
                break

        worktrees.append({
            "path": item,
            "name": item.name,
            "branch": git_info["branch"] if git_info else None,
            "commit": git_info["commit"] if git_info else None,
            "registered": registered,
            "exists": True,
        })

    return worktrees
