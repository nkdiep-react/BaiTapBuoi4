from datetime import datetime, timedelta, timezone

WAREHOUSE_TZ = timezone(timedelta(hours=7))
OPEN_HOUR = 8
CLOSE_HOUR = 18


def working_window(moment: datetime) -> tuple[datetime, datetime]:
    # giờ mở/đóng cửa (giờ VN) của ngày chứa `moment`; vào và ra đều là UTC không múi giờ
    local = moment.replace(tzinfo=timezone.utc).astimezone(WAREHOUSE_TZ)
    day_open = local.replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0)
    day_close = local.replace(hour=CLOSE_HOUR, minute=0, second=0, microsecond=0)
    return (
        day_open.astimezone(timezone.utc).replace(tzinfo=None),
        day_close.astimezone(timezone.utc).replace(tzinfo=None),
    )


def suggest_slot(docks: dict[str, list[tuple[datetime, datetime]]], earliest: datetime, duration_minutes: int):
    """Trả (mã ca, giờ bắt đầu) sớm nhất, hết chỗ trong ngày thì trả None.

    docks: {mã ca: [(bắt đầu, kết thúc), ...]} các lịch đã đặt.
    """
    open_time, close_time = working_window(earliest)
    duration = timedelta(minutes=duration_minutes)
    best = None

    for code, busy in docks.items():
        start = max(earliest, open_time)
        for busy_start, busy_end in sorted(busy):
            if busy_end <= start:
                continue
            if start + duration <= busy_start:
                break  # khoảng trống trước lịch này đủ chỗ
            start = busy_end  # lịch giao nhau hoặc nối sát nhau thì nhảy qua, giống như đã gộp lại

        if start + duration > close_time:
            continue
        if best is None or (start, code) < (best[1], best[0]):  # cùng giờ thì mã ca đứng trước
            best = (code, start)
    return best


def has_conflict(busy: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    # khoảng [start, end): lịch cũ kết thúc đúng lúc lịch mới bắt đầu thì không trùng
    return any(busy_start < end and start < busy_end for busy_start, busy_end in busy)
