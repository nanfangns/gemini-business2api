"""内存管理工具模块

提供强制内存回收功能，特别针对 Linux 环境下的 glibc malloc_trim 优化。
"""
import ctypes
import gc
import logging
import os
import platform

logger = logging.getLogger(__name__)

def trim_memory() -> None:
    """
    强制执行垃圾回收并尝试归还空闲内存给操作系统。
    
    1. 执行 Python 层的 gc.collect()。
    2. 在 Linux 系统上，调用 glibc 的 malloc_trim(0) 强制归还堆内存。
    """
    # 1. Python 层垃圾回收
    collected = gc.collect()
    logger.debug(f"[MEMORY] GC collected {collected} objects")

    # 2. 系统层内存归还 (仅限 Linux)
    if platform.system() == "Linux":
        try:
            # 加载 libc
            libc = ctypes.CDLL("libc.so.6")
            # 调用 malloc_trim(0)，强制归还所有可释放的堆内存
            # 返回 1 表示释放了内存，0 表示没有释放
            ret = libc.malloc_trim(0)
            if ret:
                logger.info("[MEMORY] malloc_trim triggered successfully (memory released to OS)")
            else:
                logger.debug("[MEMORY] malloc_trim called but no memory released")
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to call malloc_trim: {e}")
    else:
        logger.debug(f"[MEMORY] malloc_trim skipped (System: {platform.system()})")
