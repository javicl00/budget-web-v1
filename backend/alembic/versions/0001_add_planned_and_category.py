"""add planned and category_id to transactions"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = [c['name'] for c in inspector.get_columns('transactions')]
    if 'planned' not in cols:
        op.add_column('transactions', sa.Column('planned', sa.Boolean(), nullable=False, server_default='false'))
    if 'category_id' not in cols:
        op.add_column('transactions', sa.Column('category_id', sa.Integer(), nullable=True))
        op.create_foreign_key('fk_tx_category', 'transactions', 'categories', ['category_id'], ['id'])
    # ensure categories table exists (for fresh installs it already does via create_all)

def downgrade():
    op.drop_column('transactions', 'planned')
    op.drop_column('transactions', 'category_id')
