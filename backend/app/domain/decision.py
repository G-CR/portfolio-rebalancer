from calendar import monthrange
from datetime import date


def next_review(today: date, day: int, acknowledged_month: str | None):
    month = today.strftime('%Y-%m')
    due = date(today.year, today.month, min(day, monthrange(today.year, today.month)[1]))
    if acknowledged_month == month:
        year, month_num = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return date(year, month_num, min(day, monthrange(year, month_num)[1])), False
    return due, today >= due


def advance_streaks(previous: dict, directions: dict, valid: bool, local_date: str):
    if not valid:
        return {}
    result = {}
    for key, direction in directions.items():
        if not direction:
            continue
        old = previous.get(key, {})
        same = old.get('direction') == direction
        result[key] = {'direction': direction, 'count': old.get('count', 0) + 1 if same else 1,
                       'started': old.get('started', local_date) if same else local_date}
    return result


def decision_status(setup: bool, valid: bool, in_progress: bool, sustained: bool, breached: bool):
    if setup: return 'setup'
    if not valid: return 'data_issue'
    if in_progress: return 'in_progress'
    if sustained: return 'sustained'
    if breached: return 'observing'
    return 'normal'


def evidence_current(today: date, observed_date: date | None):
    return observed_date is not None and 0 <= (today - observed_date).days <= 1
