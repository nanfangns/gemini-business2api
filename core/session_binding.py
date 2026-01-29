"""
轻量化会话绑定管理器

实现 ChatID → AccountID 的固定绑定，利用 Gemini 网页端原生上下文。
"""
import asyncio
import hashlib
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def generate_chat_id(messages: list, client_ip: str = "") -> str:
    """
    生成通用 ChatID（通杀方案）
    
    策略：基于【首条消息内容 + 客户端IP】生成稳定指纹
    - 同一用户的同一个对话，首条消息不变 → ChatID 不变
    - 不同用户即使发相同消息，IP 不同 → ChatID 不同
    
    Args:
        messages: 消息列表
        client_ip: 客户端 IP 地址
    
    Returns:
        ChatID 字符串（MD5 哈希）
    """
    if not messages:
        # 空消息时用 IP + 时间戳（每次都是新对话）
        return hashlib.md5(f"{client_ip}:{time.time()}".encode()).hexdigest()
    
    # 提取首条消息的角色和内容
    first_msg = messages[0]
    role = first_msg.get("role", "")
    content = first_msg.get("content", "")
    
    # 处理多模态内容
    if isinstance(content, list):
        # 只提取文本部分
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        content = "".join(text_parts)
    
    # 标准化处理
    content = str(content).strip()[:500]  # 限制长度，避免超长消息
    
    # 生成指纹：IP + 角色 + 内容
    fingerprint = f"{client_ip}|{role}|{content}"
    return hashlib.md5(fingerprint.encode()).hexdigest()


class SessionBindingManager:
    """
    会话绑定管理器
    
    维护 ChatID → AccountID 的映射关系，支持：
    - 固定绑定：同一 ChatID 始终使用同一账号
    - 异常漂移：账号出错时自动解绑
    - 持久化：绑定关系存入数据库
    """
    
    def __init__(self, persist_interval: int = 60):
        # 内存缓存：{chat_id: {"account_id": str, "created_at": float}}
        self._bindings: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._dirty = False  # 是否有未持久化的变更
        self._persist_interval = persist_interval
        self._max_bindings = 10000  # 最大绑定数量
        self._binding_ttl = 86400 * 7  # 绑定过期时间（7天）
        
    async def get_binding(self, chat_id: str) -> Optional[str]:
        """
        获取 ChatID 对应的账号ID
        
        Returns:
            账号ID，如果未绑定则返回 None
        """
        async with self._lock:
            binding = self._bindings.get(chat_id)
            if not binding:
                return None
            
            # 检查是否过期
            if time.time() - binding.get("created_at", 0) > self._binding_ttl:
                del self._bindings[chat_id]
                self._dirty = True
                return None
            
            return binding.get("account_id")
    
    async def set_binding(self, chat_id: str, account_id: str) -> None:
        """
        设置绑定关系
        
        Args:
            chat_id: 对话ID
            account_id: 账号ID
        """
        async with self._lock:
            self._bindings[chat_id] = {
                "account_id": account_id,
                "created_at": time.time()
            }
            self._dirty = True
            
            # 检查缓存大小，LRU 清理
            if len(self._bindings) > self._max_bindings:
                self._cleanup_oldest()
        
        logger.info(f"[SESSION-BIND] 绑定 ChatID={chat_id[:8]}... → Account={account_id}")
    
    async def remove_binding(self, chat_id: str) -> bool:
        """
        解除绑定（用于异常漂移）
        
        Returns:
            是否成功解除（True=存在并已解除，False=不存在）
        """
        async with self._lock:
            if chat_id in self._bindings:
                old_account = self._bindings[chat_id].get("account_id", "unknown")
                del self._bindings[chat_id]
                self._dirty = True
                logger.info(f"[SESSION-BIND] 解绑 ChatID={chat_id[:8]}... (原账号: {old_account})")
                return True
            return False
    
    def _cleanup_oldest(self) -> None:
        """清理最旧的绑定（LRU策略）"""
        if not self._bindings:
            return
        
        # 按创建时间排序，删除最旧的 10%
        sorted_items = sorted(
            self._bindings.items(),
            key=lambda x: x[1].get("created_at", 0)
        )
        
        remove_count = max(1, len(sorted_items) // 10)
        for chat_id, _ in sorted_items[:remove_count]:
            del self._bindings[chat_id]
        
        logger.info(f"[SESSION-BIND] LRU 清理 {remove_count} 个过期绑定")
    
    async def load_from_db(self) -> None:
        """从数据库加载绑定关系"""
        try:
            from core import storage
            if not storage.is_database_enabled():
                logger.info("[SESSION-BIND] 数据库未启用，使用内存缓存模式")
                return
            
            # 使用 storage 模块的同步包装器避免事件循环冲突
            import asyncio
            data = await asyncio.to_thread(
                lambda: storage._run_in_db_loop(storage.db_get("session_bindings"))
            )
            if data and isinstance(data, dict):
                async with self._lock:
                    self._bindings = data
                logger.info(f"[SESSION-BIND] 从数据库加载 {len(data)} 个绑定")
            else:
                logger.info("[SESSION-BIND] 数据库中无绑定记录")
        except Exception as e:
            logger.error(f"[SESSION-BIND] 加载绑定失败: {e}")
    
    async def persist_to_db(self) -> bool:
        """持久化绑定关系到数据库"""
        if not self._dirty:
            return True
        
        try:
            from core import storage
            if not storage.is_database_enabled():
                return False
            
            async with self._lock:
                data = dict(self._bindings)
                self._dirty = False
            
            # 使用 storage 模块的同步包装器避免事件循环冲突
            import asyncio
            await asyncio.to_thread(
                lambda: storage._run_in_db_loop(storage.db_set("session_bindings", data))
            )
            logger.info(f"[SESSION-BIND] 持久化 {len(data)} 个绑定到数据库")
            return True
        except Exception as e:
            logger.error(f"[SESSION-BIND] 持久化失败: {e}")
            self._dirty = True  # 标记仍需持久化
            return False
    
    async def start_persist_task(self) -> None:
        """启动后台持久化任务"""
        while True:
            try:
                await asyncio.sleep(self._persist_interval)
                await self.persist_to_db()
            except asyncio.CancelledError:
                # 退出前保存
                await self.persist_to_db()
                break
            except Exception as e:
                logger.error(f"[SESSION-BIND] 持久化任务异常: {e}")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_bindings": len(self._bindings),
            "dirty": self._dirty
        }


# 全局单例
_session_binding_manager: Optional[SessionBindingManager] = None


def get_session_binding_manager() -> SessionBindingManager:
    """获取全局会话绑定管理器"""
    global _session_binding_manager
    if _session_binding_manager is None:
        _session_binding_manager = SessionBindingManager()
    return _session_binding_manager
