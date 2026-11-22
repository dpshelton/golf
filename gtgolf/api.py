"""SportsData.io HTTP client.

Every live download prints ``API-CALL:`` and the wrapper name before the
request, which is what the old single-file script printed.
"""

import json

import requests

from gtgolf import config

# One session so repeated leaderboard polls reuse the TCP connection.
_session = requests.Session()


def api_request(url):
    """GET a SportsData.io URL and parse the JSON body.

    Args:
        url: Absolute endpoint, without the ``key`` query parameter.

    Returns:
        The decoded JSON value, usually a list or a dict.

    Raises:
        requests.RequestException: The HTTP call failed.
        json.JSONDecodeError: The body was not JSON.
    """
    response = _session.get(url, params={'key': config.KEY})
    return json.loads(response.text)


def api_get_all_players():
    """Download every golfer profile.

    Returns:
        List of player profile objects.
    """
    print('API-CALL: api_get_all_players')
    return api_request(config.BASE_URL + '/golf/v2/json/Players')


def api_get_all_tournaments():
    """Download the tournament calendar.

    Returns:
        List of tournament objects.
    """
    print('API-CALL: api_get_all_tournaments')
    return api_request(config.BASE_URL + '/golf/v2/json/Tournaments')


def api_get_leaderboard(tournament_id):
    """Download one tournament leaderboard.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        Leaderboard object with ``Tournament`` and ``Players``.
    """
    print('API-CALL: api_get_leaderboard')
    return api_request(config.BASE_URL + '/golf/v2/json/Leaderboard/{}'.format(tournament_id))


def api_get_projections(tournament_id):
    """Download fantasy projections for one tournament.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        List of projection objects.
    """
    print('API-CALL: api_get_projections')
    return api_request(
        config.BASE_URL + '/golf/v2/json/PlayerTournamentProjectionStats/{}'.format(tournament_id)
    )


def api_get_dfs_slates(tournament_id):
    """Download daily-fantasy slates, including DraftKings salaries.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        List of slate objects.
    """
    print('API-CALL: api_get_dfs_slates')
    return api_request(config.BASE_URL + '/golf/v2/json/DfsSlatesByTournament/{}'.format(tournament_id))


def api_get_headshots():
    """Download hosted headshot URLs.

    Returns:
        List of headshot objects.
    """
    print('API-CALL: api_get_headshots')
    return api_request(config.BASE_URL + '/v3/golf/headshots/json/Headshots')
