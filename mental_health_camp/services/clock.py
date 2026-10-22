from datetime import datetime, timezone, timedelta

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_date(value=None):
    value = value or now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).date()
