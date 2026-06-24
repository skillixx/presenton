"""墨灵多租户归属辅助（F-B）。

presentation 是数据根实体（slide / image_asset / chat_history 均经 presentation_id 关联），
故隔离的信任边界设在 presentation：
- 创建时用当前墨灵用户**盖章**（stamp）；
- 任何「按 id 取 presentation」处校验归属（require），非本人视作 404（不泄漏存在性）；
- 列表查询按当前用户过滤。

兼容性：无墨灵身份（独立部署 / 非墨灵请求）时全部为 no-op，保持 presenton 原行为。
身份来源见 [F-A] utils.molin_context.get_molin_identity。
"""

from typing import Optional

from fastapi import HTTPException

from utils.molin_context import get_molin_identity


def current_owner_id() -> Optional[str]:
    """当前请求的墨灵用户 ID；非墨灵请求返回 None。"""
    identity = get_molin_identity()
    return identity.user_id if identity else None


def stamp_owner(presentation) -> None:
    """创建/复制 presentation 时盖章归属。非墨灵请求不改动（user_id 保持 None）。"""
    owner = current_owner_id()
    if owner is not None:
        presentation.user_id = owner


def require_owner(presentation) -> None:
    """校验 presentation 归属当前墨灵用户；非本人抛 404（与「不存在」一致，避免泄漏存在性）。

    - 非墨灵请求（无身份）：放行，保持原行为。
    - presentation 为 None：交由调用方原有的 404 逻辑处理，这里不抢先报错。
    """
    owner = current_owner_id()
    if owner is None or presentation is None:
        return
    if getattr(presentation, "user_id", None) != owner:
        raise HTTPException(status_code=404, detail="Presentation not found")
