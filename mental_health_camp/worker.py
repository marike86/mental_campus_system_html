"""Run exactly one standalone process: python worker.py [--once]."""
import argparse
import logging
import signal
import threading
from database import SessionLocal
from migrate import require_current_schema
from services.inbox import overdue_scan


def scan():
    with SessionLocal() as db:
        count = overdue_scan(db)
        db.commit()
        return count


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args=parser.parse_args()
    require_current_schema()
    stopping=threading.Event()
    signal.signal(signal.SIGINT, lambda *_:stopping.set())
    signal.signal(signal.SIGTERM, lambda *_:stopping.set())
    while not stopping.is_set():
        try:
            logging.warning('超时扫描完成：%s 项', scan())
        except Exception:
            logging.exception('超时扫描失败，下一周期重试')
            if args.once:
                raise
        if args.once:
            break
        stopping.wait(300)
