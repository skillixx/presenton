"""墨灵 F-B（多租户归属）单元测试。

覆盖 stamp_owner / require_owner / current_owner_id 在「有/无墨灵身份」下的行为。
用轻量假对象（带 user_id 属性）即可，不依赖 DB / ORM。
"""

import pytest
from fastapi import HTTPException

from utils.molin_context import (
    MolinIdentity,
    reset_molin_identity,
    set_molin_identity,
)
from utils.molin_tenancy import current_owner_id, require_owner, stamp_owner


class _Doc:
    """模拟带 user_id 的数据对象（presentation / image_asset）。"""

    def __init__(self, user_id=None):
        self.user_id = user_id


def _with_identity(user_id):
    return set_molin_identity(MolinIdentity(user_id=user_id, llm_api_key="sk"))


# ---- 无墨灵身份（独立部署 / 非墨灵请求）：全部 no-op，保持原行为 ----

def test_no_identity_is_noop():
    assert current_owner_id() is None
    doc = _Doc(user_id=None)
    stamp_owner(doc)
    assert doc.user_id is None  # 不盖章
    # 即使归属不一致，无身份时也放行（不抛）
    require_owner(_Doc(user_id="someone-else"))


# ---- 有墨灵身份：盖章 + 归属校验生效 ----

def test_stamp_sets_owner():
    token = _with_identity("u1")
    try:
        assert current_owner_id() == "u1"
        doc = _Doc()
        stamp_owner(doc)
        assert doc.user_id == "u1"
    finally:
        reset_molin_identity(token)


def test_require_owner_allows_self():
    token = _with_identity("u1")
    try:
        require_owner(_Doc(user_id="u1"))  # 本人，不抛
    finally:
        reset_molin_identity(token)


def test_require_owner_rejects_others_as_404():
    token = _with_identity("u1")
    try:
        with pytest.raises(HTTPException) as exc:
            require_owner(_Doc(user_id="u2"))
        assert exc.value.status_code == 404  # 非本人按「不存在」处理，不泄漏存在性
    finally:
        reset_molin_identity(token)


def test_require_owner_rejects_unowned_legacy_rows():
    """墨灵用户访问无归属（user_id=None，老数据/独立部署遗留）的对象 → 404。"""
    token = _with_identity("u1")
    try:
        with pytest.raises(HTTPException) as exc:
            require_owner(_Doc(user_id=None))
        assert exc.value.status_code == 404
    finally:
        reset_molin_identity(token)


def test_require_owner_none_presentation_is_noop():
    """presentation 为 None 时不抢先报错，交由调用方原有 404 处理。"""
    token = _with_identity("u1")
    try:
        require_owner(None)  # 不抛
    finally:
        reset_molin_identity(token)
