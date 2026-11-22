"""Eastern tee times shown in Pacific, and the "updated ago" clock text.

SportsData tee times are Eastern. ``convert_tee_time`` subtracts three hours.
Passing the returned datetime through again shifts it another three hours, so
display code converts the original string once.
"""

from datetime import datetime, timedelta


def get_last_updated_str(last_updated):
    """Describe how long ago the leaderboard was written.

    Args:
        last_updated: Row with ``LeaderboardLastUpdated`` as
            ``YYYY-MM-DD HH:MM:SS``.

    Returns:
        Tuple of ``(display text, total seconds)``. The text drops hour or
        minute fields when they are zero.
    """
    delta_time = datetime.now() - datetime.fromisoformat(last_updated['LeaderboardLastUpdated'])
    hours, remainder = divmod(delta_time.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours == 0 and minutes == 0:
        text = 'Updated {}s ago'.format(int(seconds))
    elif hours == 0:
        text = 'Updated {}m {}s ago'.format(int(minutes), int(seconds))
    else:
        text = 'Updated {}h {}m {}s ago'.format(int(hours), int(minutes), int(seconds))
    return text, delta_time.total_seconds()


def get_seconds_since_tee_time(tee_time):
    """Seconds from ``tee_time`` until now.

    Args:
        tee_time: A datetime. Future tee times return a negative number.

    Returns:
        Float seconds.
    """
    return (datetime.now() - tee_time).total_seconds()


def convert_tee_time(tee_time):
    """Shift an Eastern tee time three hours earlier for Pacific display.

    Args:
        tee_time: ISO string, datetime, the sentinel ``"None"``, or None.

    Returns:
        A datetime for a real timestamp. ``None`` and ``"None"`` are returned
        unchanged. Passing the returned datetime through again shifts it
        another three hours.
    """
    if type(tee_time) is datetime:
        return tee_time - timedelta(hours=3)
    if type(tee_time) is str and tee_time != 'None':
        return datetime.fromisoformat(tee_time) - timedelta(hours=3)
    return tee_time


def get_time_str(value):
    """Format a tee time as ``h:mmAM`` or ``h:mmPM`` with no leading zero.

    Args:
        value: datetime, ISO string, ``"None"``, or None. Strings are not
            shifted; call ``convert_tee_time`` first when the source is Eastern.

    Returns:
        Display text, or ``"None"`` when there is no clock time.
    """
    if type(value) is datetime:
        return value.strftime('%-I:%M%p')
    if value is not None and value != 'None':
        return datetime.fromisoformat(value).strftime('%-I:%M%p')
    return 'None'


def annotate_leaderboard(leaderboard):
    """Copy leaderboard rows and add the tee-time fields the results page shows.

    SportsData tee times are Eastern and are shifted three hours earlier for
    Pacific display. The feed never sends ``F``. A golfer whose tee time was
    more than an hour ago and who has no holes-through value is shown as
    finished.

    Args:
        leaderboard: sqlite rows or mappings.

    Returns:
        List of plain dicts in the same order.
    """
    annotated = []
    for row in leaderboard:
        player = dict(row)
        tee_time = player['TeeTime']
        if tee_time is not None and tee_time != 'None':
            # convert_tee_time shifts any datetime it receives, so the original
            # string has to be converted once and then reused.
            converted = convert_tee_time(tee_time)
            player['SecondsSinceTeeTime'] = get_seconds_since_tee_time(converted)
            player['TeeTime'] = get_time_str(converted)
            through = player['TotalThrough']
            if (through is None or through == 'None') and player['SecondsSinceTeeTime'] > 3600:
                player['TotalThrough'] = 'F'
        annotated.append(player)
    return annotated


def _extreme_tee_time(leaderboard, round_num, earliest):
    """Find the first or last tee time in a round.

    Args:
        leaderboard: Raw API leaderboard, whose players carry ``Rounds``.
        round_num: 1-based round number.
        earliest: True for the first tee time, False for the last.

    Returns:
        A Pacific datetime, or None when that round has no posted times.
    """
    extreme = None
    for player in leaderboard['Players']:
        rounds = player['Rounds']
        if len(rounds) < round_num:
            continue
        tee_time = convert_tee_time(rounds[round_num - 1]['TeeTime'])
        if tee_time is None:
            continue
        if extreme is None or (tee_time < extreme if earliest else tee_time > extreme):
            extreme = tee_time
    return extreme


def get_first_tee_time(leaderboard, round_num):
    """Return the earliest Pacific tee time for ``round_num``, or None.

    Args:
        leaderboard: Raw API leaderboard.
        round_num: 1-based round number.

    Returns:
        datetime or None.
    """
    return _extreme_tee_time(leaderboard, round_num, earliest=True)


def get_last_tee_time(leaderboard, round_num):
    """Return the latest Pacific tee time for ``round_num``, or None.

    Args:
        leaderboard: Raw API leaderboard.
        round_num: 1-based round number.

    Returns:
        datetime or None.
    """
    return _extreme_tee_time(leaderboard, round_num, earliest=False)
