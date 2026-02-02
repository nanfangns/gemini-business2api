"""
全局并发控制模块
用于限制资源密集型操作（如浏览器实例）的并发数
"""
import threading

# 全局浏览器锁
# 限制同时只能运行一个浏览器实例，防止内存爆炸（特别是 Zeabur 512MB 限制下）
# 使用 threading.Lock 而不是 asyncio.Lock，因为 GeminiAutomation 是同步运行在线程池中的
BROWSER_LOCK = threading.Lock()
