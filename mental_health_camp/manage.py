"""Offline maintenance commands; requires access to the application database."""
import argparse
from database import SessionLocal
from models.user import User
from migrate import require_current_schema


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    promote=commands.add_parser('promote-super-admin')
    promote.add_argument('--email',required=True)
    args=parser.parse_args()
    require_current_schema()
    with SessionLocal() as db:
        user=db.query(User).filter_by(email=args.email).first()
        if not user or user.role not in ('admin','super_admin'):
            parser.error('只能提升现有管理员账号')
        user.role='super_admin'
        db.commit()
    print('超级管理员设置完成')
