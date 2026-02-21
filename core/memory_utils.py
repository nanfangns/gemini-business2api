"""轻量内存回收工具。"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import sys

logger = logging.getLogger("gemini.memory")


def trim_process_memory(reason: str = "unknown") -> bool:
    """
    触发一次进程级内存回收。

    1) 先执行 Python GC，清理可回收对象。
    2) 在 Linux + glibc 上尝试调用 malloc_trim(0) 将空闲堆归还给 OS。
    """
    gc.collect()

    platform_tag = f"os={os.name}, platform={sys.platform}"

    if os.name != "posix":
        logger.info("[MEMORY] trim skipped (non-posix): reason=%s, %s", reason, platform_tag)
        return False

    try:
        libc = ctypes.CDLL("libc.so.6")
        if hasattr(libc, "malloc_trim"):
            result = int(libc.malloc_trim(0))
            logger.info(
                "[MEMORY] malloc_trim executed: reason=%s, result=%s, %s",
                reason,
                result,
                platform_tag,
            )
            return result == 1

        logger.info("[MEMORY] malloc_trim unavailable in libc: reason=%s, %s", reason, platform_tag)
    except Exception as exc:
        logger.debug("[MEMORY] malloc_trim unavailable: reason=%s, %s, err=%s", reason, platform_tag, exc)

    return False

