"""Web 安全辅助：变更类接口鉴权与本机限制。"""

from __future__ import annotations

from ipaddress import ip_address

from flask import current_app, jsonify, request


def _is_loopback(addr: str | None) -> bool:
    if not addr:
        return False
    host = str(addr).split(",")[0].strip()
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _extract_api_token() -> str:
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.headers.get("X-API-Token", "").strip()


def require_mutation_auth(action_name: str):
    """
    校验“触发脚本执行”类接口权限。

    规则：
    1) 配置了 `MFTS_API_WRITE_TOKEN` 时，必须携带正确 token。
    2) 未配置 token 时，默认只允许本机回环地址（LOCAL_ONLY=true）。
    """
    cfg = current_app.config
    logger = cfg.get("MFTS_LOGGER")
    remote_addr = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()

    configured_token = str(cfg.get("API_WRITE_TOKEN", "") or "").strip()
    local_only = bool(cfg.get("LOCAL_ONLY", True))

    if configured_token:
        provided = _extract_api_token()
        if provided != configured_token:
            if logger:
                logger.warning("拒绝 %s：token 无效，remote=%s", action_name, remote_addr)
            return False, (
                jsonify(
                    {
                        "success": False,
                        "error": "未授权：缺少或无效的 API Token",
                        "hint": "请在请求头设置 X-API-Token 或 Authorization: Bearer <token>",
                    }
                ),
                401,
            )
        return True, None

    # 未配置 token：默认仅本机可调用变更类接口
    if local_only and _is_loopback(remote_addr):
        return True, None

    if logger:
        logger.warning("拒绝 %s：未配置 token 且请求非本机，remote=%s", action_name, remote_addr)
    return False, (
        jsonify(
            {
                "success": False,
                "error": "未授权：该接口仅允许本机调用",
                "hint": "设置 MFTS_API_WRITE_TOKEN 后可远程调用（需携带 token）",
            }
        ),
        403,
    )

