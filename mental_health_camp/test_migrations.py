"""Run migrations in isolated subprocesses; never touch the checked-in databases."""
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

ROOT=Path(__file__).parent


def command(path, *args):
    env=dict(os.environ,DATABASE_URL='sqlite:///'+path.as_posix(),PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable,*args],cwd=ROOT,env=env,text=True,capture_output=True,encoding='utf-8',errors='replace')


def legacy(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE users(id INTEGER PRIMARY KEY,email VARCHAR NOT NULL,nickname VARCHAR NOT NULL,hashed_password VARCHAR NOT NULL,role VARCHAR NOT NULL,notification_enabled BOOLEAN,student_id VARCHAR,college VARCHAR,grade VARCHAR,last_login DATETIME,created_at DATETIME);
        CREATE TABLE bootcamps(id INTEGER PRIMARY KEY,name VARCHAR NOT NULL,description TEXT,days INTEGER NOT NULL,is_active BOOLEAN,created_by INTEGER NOT NULL,created_at DATETIME);
        CREATE TABLE enrollments(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,bootcamp_id INTEGER NOT NULL,batch_id INTEGER,status VARCHAR NOT NULL DEFAULT 'approved',start_date DATE,created_at DATETIME);
        CREATE UNIQUE INDEX uq_enrollment_camp ON enrollments(user_id,bootcamp_id);
        CREATE TABLE day_forms(id INTEGER PRIMARY KEY,bootcamp_id INTEGER NOT NULL,day_number INTEGER NOT NULL,questions JSON NOT NULL);
        CREATE TABLE submissions(id INTEGER PRIMARY KEY,enrollment_id INTEGER NOT NULL,day_number INTEGER NOT NULL,answers TEXT NOT NULL,submitted_at DATETIME);
        CREATE TABLE review_assignments(id INTEGER PRIMARY KEY,submission_id INTEGER NOT NULL,reviewer_id INTEGER NOT NULL,assigned_by INTEGER,assignment_type VARCHAR,status VARCHAR,assigned_at DATETIME,completed_at DATETIME);
        INSERT INTO users(id,email,nickname,hashed_password,role) VALUES(1,'legacy@example.com','Legacy','unused','user');
        INSERT INTO bootcamps(id,name,days,is_active,created_by) VALUES(1,'Legacy',1,1,1);
        INSERT INTO enrollments(id,user_id,bootcamp_id,start_date) VALUES(1,1,1,'2026-01-01');
        INSERT INTO day_forms(id,bootcamp_id,day_number,questions) VALUES(1,1,1,'[{"id":"text","type":"text","label":"Original"}]');
        INSERT INTO submissions(id,enrollment_id,day_number,answers,submitted_at) VALUES(1,1,1,'{"text":"original"}','2026-01-01 01:00:00');
        """)


def test_legacy_upgrade_idempotence_backup_restore(tmp_path):
    path=tmp_path/'legacy.db';legacy(path)
    backup=tmp_path/'before.backup'
    result=command(path,'migrate.py','--backup',str(backup))
    assert result.returncode==0,result.stderr
    assert backup.exists()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM workflow_schema').fetchone()==(2,)
        assert db.execute('SELECT count(*) FROM submission_attempts').fetchone()==(1,)
        assert db.execute('SELECT legacy FROM day_form_versions').fetchone()==(1,)
        assert db.execute('SELECT started_at FROM enrollment_days').fetchone()==(None,)
        assert db.execute('SELECT count(*) FROM notifications').fetchone()==(0,)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE day_form_versions SET questions='[]'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('DELETE FROM day_form_versions')
    again=command(path,'migrate.py')
    assert again.returncode==0 and '最新' in again.stdout
    restored=tmp_path/'restored.db';shutil.copy2(backup,restored)
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='workflow_schema'").fetchone()==(0,)
        assert db.execute('SELECT answers FROM submissions').fetchone()[0]=='{"text":"original"}'
    assert command(restored,'migrate.py').returncode==0


@pytest.mark.parametrize('corruption',['duplicate','orphan'])
def test_preflight_aborts_without_mutating_legacy(tmp_path,corruption):
    path=tmp_path/'legacy.db';legacy(path)
    with sqlite3.connect(path) as db:
        if corruption=='duplicate':
            db.execute('DROP INDEX uq_enrollment_camp')
            db.execute('INSERT INTO enrollments(user_id,bootcamp_id,status) VALUES(1,1,"approved")')
        else:
            db.execute('UPDATE submissions SET enrollment_id=999')
    before=path.read_bytes()
    result=command(path,'migrate.py')
    assert result.returncode!=0
    assert 'ID' in result.stderr
    assert path.read_bytes()==before


def test_fresh_install_schema_guard_and_upgrade_from_v1(tmp_path):
    path=tmp_path/'fresh.db'
    assert command(path,'-c','from migrate import require_current_schema;require_current_schema()').returncode!=0
    assert command(path,'migrate.py').returncode==0
    with sqlite3.connect(path) as db:
        db.execute('UPDATE workflow_schema SET version=1')
        db.execute('DROP TABLE participation_days')
        db.execute('DROP TABLE metrics_coverage')
    assert command(path,'-c','from migrate import require_current_schema;require_current_schema()').returncode!=0
    assert command(path,'migrate.py').returncode==0
    assert command(path,'-c','from migrate import require_current_schema;require_current_schema()').returncode==0
