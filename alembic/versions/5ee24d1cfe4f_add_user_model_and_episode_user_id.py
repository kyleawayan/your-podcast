"""add user model and episode user_id

Revision ID: 5ee24d1cfe4f
Revises: 461852330cee
Create Date: 2026-02-03 21:57:51.309393

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ee24d1cfe4f'
down_revision: Union[str, Sequence[str], None] = '461852330cee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed UUID for the "global" user so it's deterministic
GLOBAL_USER_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create users table
    op.create_table('users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 2. Create the "global" user
    op.execute(
        sa.text(
            "INSERT INTO users (id, name) VALUES (:id, :name)"
        ).bindparams(id=GLOBAL_USER_ID, name='global')
    )

    # 3. Add user_id column as nullable first
    op.add_column('episodes', sa.Column('user_id', sa.UUID(), nullable=True))

    # 4. Assign all existing episodes to the global user
    op.execute(
        sa.text(
            "UPDATE episodes SET user_id = :user_id WHERE user_id IS NULL"
        ).bindparams(user_id=GLOBAL_USER_ID)
    )

    # 5. Make user_id NOT NULL and add FK constraint
    op.alter_column('episodes', 'user_id', nullable=False)
    op.create_foreign_key('fk_episodes_user_id', 'episodes', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_episodes_user_id', 'episodes', type_='foreignkey')
    op.drop_column('episodes', 'user_id')
    op.drop_table('users')
