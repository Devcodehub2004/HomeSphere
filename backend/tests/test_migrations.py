"""Opt-in real PostgreSQL migration checks; never point at a personal database."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture
def migration_db(monkeypatch):
    url = os.getenv("HOMESPHERE_MIGRATION_TEST_URL")
    if not url:
        pytest.skip("Set HOMESPHERE_MIGRATION_TEST_URL to an isolated homesphere_test_* database")
    assert (make_url(url).database or '').startswith('homesphere_test_')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text('DROP SCHEMA public CASCADE'))
        connection.execute(text('CREATE SCHEMA public'))
    monkeypatch.setenv('DATABASE_URL', url)
    yield engine, Config('alembic.ini')
    engine.dispose()


def test_fresh_database_migrates_to_matching_head(migration_db):
    engine, config = migration_db
    command.upgrade(config, 'head')
    command.check(config)
    with engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'c84e72a190fd'
        assert db.scalar(text('SELECT count(*) FROM files')) == 0


def test_upgrade_preserves_existing_rows_and_refuses_unowned_files(migration_db):
    engine, config = migration_db
    command.upgrade(config, '96963c861318')
    with engine.begin() as db:
        db.execute(text("INSERT INTO homes (name,city,created_at) VALUES ('Keep','Local',CURRENT_TIMESTAMP)"))
        db.execute(text("""INSERT INTO files (id,storage_key,name,size_bytes,content_type,sha256,state,created_at)
            VALUES ('7bf645ad-858e-452c-9699-36a35407c397', '0123456789abcdef0123456789abcdef',
                    'keep.txt',4,'text/plain',:sha,'ready',CURRENT_TIMESTAMP)"""), {'sha': 'a' * 64})
    with pytest.raises(RuntimeError, match='Provision the single owner'):
        command.upgrade(config, 'head')
    with engine.begin() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '96963c861318'
        db.execute(text("INSERT INTO owners (id,username,password_hash,created_at) VALUES (1,'demo','unchanged-hash',CURRENT_TIMESTAMP)"))
        before = db.execute(text('SELECT * FROM files')).mappings().one()
    command.upgrade(config, 'head')
    command.check(config)
    with engine.connect() as db:
        after = db.execute(text('SELECT * FROM files')).mappings().one()
        assert all(after[key] == value for key, value in before.items())
        assert after['owner_id'] == 1 and after['folder_id'] is None and after['deleted_at'] is None
        assert db.scalar(text('SELECT name FROM homes')) == 'Keep'
        assert db.scalar(text('SELECT password_hash FROM owners')) == 'unchanged-hash'
    with pytest.raises(RuntimeError, match='restore the pre-upgrade backup'):
        command.downgrade(config, '96963c861318')
