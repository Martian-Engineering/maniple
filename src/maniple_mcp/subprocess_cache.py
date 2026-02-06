"""
Subprocess Caching Utilities for Claude Team MCP

Provides caching for expensive subprocess calls like system_profiler
to avoid repeated execution during startup and normal operation.
"""

import logging
import subprocess
import time
from typing import Optional

logger = logging.getLogger("claude-team-mcp.subprocess_cache")


# =============================================================================
# Cache Configuration
# =============================================================================

# Time-to-live for cached results in seconds (5 minutes)
CACHE_TTL_SECONDS = 300

# Module-level cache: maps command string to (result_stdout, timestamp)
_cache: dict[str, tuple[str, float]] = {}


# =============================================================================
# Cached System Profiler
# =============================================================================


def cached_system_profiler(
    data_type: str,
    timeout: int = 5,
) -> Optional[str]:
    """
    Run system_profiler with caching to avoid repeated slow calls.

    The result is cached for CACHE_TTL_SECONDS (5 minutes) to avoid
    repeated calls during startup and normal operation. system_profiler
    is notoriously slow and the data it returns (display info, fonts)
    rarely changes during a session.

    Args:
        data_type: The data type to query (e.g., "SPDisplaysDataType", "SPFontsDataType")
        timeout: Subprocess timeout in seconds (default 5)

    Returns:
        The stdout from system_profiler, or None if the call failed/timed out
    """
    cache_key = f"system_profiler {data_type}"
    current_time = time.time()

    # Check cache for valid entry
    if cache_key in _cache:
        cached_result, cached_time = _cache[cache_key]
        age = current_time - cached_time
        if age < CACHE_TTL_SECONDS:
            logger.debug(
                f"Cache hit for '{cache_key}' (age: {age:.1f}s, TTL: {CACHE_TTL_SECONDS}s)"
            )
            return cached_result
        else:
            logger.debug(f"Cache expired for '{cache_key}' (age: {age:.1f}s)")

    # Cache miss or expired - run the command
    logger.debug(f"Cache miss for '{cache_key}', running subprocess")
    try:
        result = subprocess.run(
            ["system_profiler", data_type],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout

        # Cache the result
        _cache[cache_key] = (stdout, current_time)
        logger.debug(f"Cached result for '{cache_key}'")

        return stdout

    except subprocess.TimeoutExpired:
        logger.warning(f"system_profiler {data_type} timed out after {timeout}s")
        return None
    except Exception as e:
        logger.warning(f"system_profiler {data_type} failed: {e}")
        return None


def clear_cache() -> None:
    """
    Clear all cached subprocess results.

    Useful for testing or when cache invalidation is needed.
    """
    global _cache
    _cache.clear()
    logger.debug("Subprocess cache cleared")


def get_cache_stats() -> dict:
    """
    Get statistics about the current cache state.

    Returns:
        Dict with cache statistics (entry count, keys, ages)
    """
    current_time = time.time()
    stats = {
        "entry_count": len(_cache),
        "entries": {},
    }
    for key, (_, timestamp) in _cache.items():
        stats["entries"][key] = {
            "age_seconds": current_time - timestamp,
            "expires_in_seconds": max(0, CACHE_TTL_SECONDS - (current_time - timestamp)),
        }
    return stats
