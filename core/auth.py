"""
API认证模块
提供API Key验证功能（用于API端点）
管理端点使用Session认证（见core/session_auth.py）
"""
from typing import Optional
from fastapi import HTTPException


import logging
from core.config import BasicConfig, ApiKeyConfig, ApiKeyMode

logger = logging.getLogger(__name__)

def verify_api_key(authorization: Optional[str], basic_config: BasicConfig) -> ApiKeyConfig:
    """
    验证 API Key 并返回配置对象
    """
    # 1. 提取 Token
    token = ""
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()
            
    # 2. 检查是否完全未配置 Key (开放模式)
    legacy_key = basic_config.api_key
    has_legacy = bool(legacy_key)
    has_new = bool(basic_config.api_keys)
    
    # Debug Logging
    # logger.debug(f"[AUTH] Verifying. HasLegacy={has_legacy}, Count={len(basic_config.api_keys)}")
    
    if not has_legacy and not has_new:
        return ApiKeyConfig(key="default", mode=ApiKeyMode.MEMORY, remark="Open Access")
        
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    # 4. 匹配 Legacy Key
    if has_legacy and token == legacy_key:
        return ApiKeyConfig(key=legacy_key, mode=ApiKeyMode.MEMORY, remark="Legacy Key")
        
    # 5. 匹配 New Keys
    if has_new:
        for key_cfg in basic_config.api_keys:
            # 兼容 Pydantic 对象和字典（防止配置加载异常）
            k_val = getattr(key_cfg, 'key', None) or (key_cfg.get('key') if isinstance(key_cfg, dict) else None)
            
            if k_val == token:
                # 如果是字典，转换回对象
                if isinstance(key_cfg, dict):
                    try:
                        return ApiKeyConfig(**key_cfg)
                    except:
                        pass
                else:
                    return key_cfg
                
    # 6. 验证失败
    logger.warning(f"[AUTH] Key verify failed. Token={token[:6]}... LegacyMatch=False, NewKeys={len(basic_config.api_keys)}")
    raise HTTPException(status_code=401, detail="Invalid API Key")
