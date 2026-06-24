"""add user_id to presentations and imageasset (Molin F-B multi-tenancy)

Revision ID: b7c1a9d2e3f4
Revises: c7b70d0f31b1
Create Date: 2026-06-24 16:00:00.000000

墨灵多租户归属：为 presentations 与 imageasset 增加 user_id 列 + 索引。
可空以兼容独立部署。幂等：重复执行时跳过已存在的列/索引。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7c1a9d2e3f4'
down_revision: Union[str, None] = 'c7b70d0f31b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMN = 'user_id'
# (表名, 索引名)：均为 F-B 加 user_id 的目标表。
_TARGETS = [
    ('presentations', 'ix_presentations_user_id'),
    ('imageasset', 'ix_imageasset_user_id'),
]


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {c['name'] for c in inspector.get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index in {i['name'] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    for table, index in _TARGETS:
        if not _has_column(table, _COLUMN):
            op.add_column(
                table,
                sa.Column(_COLUMN, sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            )
        if not _has_index(table, index):
            op.create_index(op.f(index), table, [_COLUMN], unique=False)


def downgrade() -> None:
    for table, index in _TARGETS:
        if _has_index(table, index):
            op.drop_index(op.f(index), table_name=table)
        if _has_column(table, _COLUMN):
            op.drop_column(table, _COLUMN)
