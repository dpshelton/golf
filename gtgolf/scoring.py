"""Pool points and the competition-ranking leaderboard parse."""

from gtgolf import config
from gtgolf.profiles import _profile_indexes


def _rank_points_lookup(table):
    """Expand inclusive place bands into a rank-to-points map.

    Args:
        table: Sequence of ``(start, end, points)`` bands.

    Returns:
        Dict mapping every integer rank in those bands to its points.
    """
    lookup = {}
    for start, end, points in table:
        for rank in range(start, end + 1):
            lookup[rank] = points
    return lookup


_POINTS_BY_RANK = _rank_points_lookup(config.POINTS)
_ONE_AND_DONE_BY_RANK = _rank_points_lookup(config.ONE_N_DONE_POINTS)


def get_points(rank, one_n_done=False, major=False):
    """Convert a finishing position into pool points.

    Args:
        rank: 1-based place, or None when the golfer has no score. Integer
            ranks use a precomputed table. Other numbers, including ``True``,
            still walk the inclusive bands.
        one_n_done: Use ``ONE_N_DONE_POINTS`` instead of ``POINTS``.
        major: Multiply the award by ``MAJOR_MULTIPLIER``.

    Returns:
        Point value. Missing ranks and places outside the table score 0.
    """
    multiplier = config.MAJOR_MULTIPLIER if major else 1
    if rank is None:
        return 0
    # bool is a subclass of int, but type(True) is bool. Keep the old band walk
    # for those values so True still scores like a first-place finish.
    if type(rank) is int:
        table = _ONE_AND_DONE_BY_RANK if one_n_done else _POINTS_BY_RANK
        return table.get(rank, 0) * multiplier

    bands = config.ONE_N_DONE_POINTS if one_n_done else config.POINTS
    for start, end, points in bands:
        if start <= rank <= end:
            return points * multiplier
    return 0


def _leaderboard_row(player, profile, rank):
    """Build one stored leaderboard record.

    Args:
        player: Raw leaderboard player from the API.
        profile: Matching profile. Missing profiles raise, as they always did.
        rank: Integer place, or None.

    Returns:
        Mapping ready to insert. Missing scores and tee times become the
        string ``"None"`` so the templates can compare against that sentinel.
    """
    return {
        'PlayerID': player['PlayerID'],
        'Rank': str(rank),
        'DraftKingsPlayerID': profile['DraftKingsPlayerID'],
        'DraftKingsName': profile['DraftKingsName'],
        'Points': str(get_points(rank, one_n_done=False, major=config.MAJOR)),
        'OneAndDonePoints': str(get_points(rank, one_n_done=True, major=config.MAJOR)),
        'TotalThrough': player['TotalThrough'] if player['TotalThrough'] is not None else 'None',
        'TeeTime': player['TeeTime'] if player['TeeTime'] is not None else 'None',
    }


def parse_leaderboard(leaderboard, player_profiles):
    """Turn a SportsData leaderboard into pool rows.

    The feed's own rank is not used. Golfers who have a total score keep the
    API's order and take competition ranking: a tie keeps the place of the
    first golfer with that score, and the next different score skips the
    tied places. Golfers with no score are appended afterward as rank
    ``"None"``, even if they sat between scored golfers in the feed.

    Args:
        leaderboard: Leaderboard JSON object. ``Players`` must already be grouped
            so equal scores are adjacent; this function does not re-sort.
        player_profiles: Profiles that supply DraftKings ids and names.

    Returns:
        Ranked rows followed by unranked rows.
    """
    by_id = _profile_indexes(player_profiles)['by_player_id']
    ranked = []
    unranked = []
    ranked_player_count = 0
    previous_score = None
    current_rank = 1

    for player in leaderboard['Players']:
        profile = by_id.get(player['PlayerID'])
        if player['TotalScore'] is not None:
            ranked_player_count += 1
            if player['TotalScore'] != previous_score:
                current_rank = ranked_player_count
            previous_score = player['TotalScore']
            ranked.append(_leaderboard_row(player, profile, current_rank))
        else:
            unranked.append(_leaderboard_row(player, profile, None))

    return ranked + unranked
