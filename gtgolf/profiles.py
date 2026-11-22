"""Local golfer profiles and headshots.

``player_profiles.json`` is several megabytes, so parses are reused until the
file's size or mtime changes. Callers must treat a cached list as read-only.
"""

import json
import os

from gtgolf import api, config

# path -> (mtime_ns, size), parsed JSON.
_json_cache = {}
# id(profile_list) -> (list, indexes). Invalidated when a new list is loaded.
_profile_index_cache = {}


def _profile_indexes(player_profiles):
    """Index profiles by id and DraftKings name, keeping the first duplicate.

    The first match is the one a forward scan would return. DraftKings names
    are not unique (two ``Jamal Hossain`` rows, for example).

    Args:
        player_profiles: Profile mappings.

    Returns:
        Dict with ``by_player_id``, ``by_dk_id``, and ``by_name``.
    """
    cached = _profile_index_cache.get(id(player_profiles))
    if cached is not None and cached[0] is player_profiles:
        return cached[1]

    by_player_id = {}
    by_dk_id = {}
    by_name = {}
    for profile in player_profiles:
        by_player_id.setdefault(profile['PlayerID'], profile)
        dk_id = profile['DraftKingsPlayerID']
        if dk_id is not None:
            by_dk_id.setdefault(dk_id, profile)
        # None names are indexed too, so a lookup for None still returns the first.
        by_name.setdefault(profile['DraftKingsName'], profile)

    indexes = {
        'by_player_id': by_player_id,
        'by_dk_id': by_dk_id,
        'by_name': by_name,
    }
    _profile_index_cache[id(player_profiles)] = (player_profiles, indexes)
    return indexes


def get_player_profile(player_id=None, draft_kings_player_id=None, player_profiles=None):
    """Find one profile by SportsData id, DraftKings id, or either.

    When both ids are passed, the earliest profile in ``player_profiles`` that
    matches either id wins. That is the same rule as scanning the list once.

    Args:
        player_id: SportsData ``PlayerID``, or None to skip that key.
        draft_kings_player_id: DraftKings id, or None to skip that key.
        player_profiles: Profile mappings to search.

    Returns:
        The matching profile, or None when neither id hits.
    """
    if player_id is not None and draft_kings_player_id is not None:
        for profile in player_profiles:
            if player_id == profile['PlayerID'] or draft_kings_player_id == profile['DraftKingsPlayerID']:
                return profile
        return None

    indexes = _profile_indexes(player_profiles)
    if player_id is not None:
        return indexes['by_player_id'].get(player_id)
    if draft_kings_player_id is not None:
        return indexes['by_dk_id'].get(draft_kings_player_id)
    return None


def get_player_id_from_name(player_name, player_profiles):
    """Resolve a DraftKings display name to a SportsData player id.

    Args:
        player_name: ``DraftKingsName``. The first row wins when names repeat.
        player_profiles: Profile mappings to search.

    Returns:
        ``PlayerID``, or None when the name is absent.
    """
    profile = _profile_indexes(player_profiles)['by_name'].get(player_name)
    if profile is None:
        return None
    return profile['PlayerID']


def _load_json(path):
    """Read JSON from ``path``, reusing the parse while the file is unchanged.

    Args:
        path: Filesystem path.

    Returns:
        The decoded JSON value. Callers must treat a cached list as read-only.
    """
    stat_result = os.stat(path)
    cache_key = (stat_result.st_mtime_ns, stat_result.st_size)
    cached = _json_cache.get(path)
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    with open(path, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    _json_cache[path] = (cache_key, payload)
    return payload


def _write_json(path, payload):
    """Write ``payload`` as compact JSON and refresh the read cache.

    Args:
        path: Destination path. The file is replaced in place.
        payload: JSON-serializable value.
    """
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle)
    stat_result = os.stat(path)
    _json_cache[path] = ((stat_result.st_mtime_ns, stat_result.st_size), payload)


def fetch_player_profiles():
    """Download every profile and overwrite ``player_profiles.json``.

    Returns:
        The profile list that was written.
    """
    player_profiles = api.api_get_all_players()
    _write_json(config.PLAYERS_FILENAME, player_profiles)
    return player_profiles


def load_player_profiles():
    """Load ``player_profiles.json``.

    Returns:
        List of profile mappings. Repeated calls return the same list until
        the file changes.
    """
    return _load_json(config.PLAYERS_FILENAME)


def fetch_headshots():
    """Download headshots and overwrite ``headshots.json``.

    Returns:
        The headshot list that was written.
    """
    headshots = api.api_get_headshots()
    _write_json(config.HEADSHOTS_FILENAME, headshots)
    return headshots


def load_headshots():
    """Load ``headshots.json``.

    Returns:
        List of headshot mappings.
    """
    return _load_json(config.HEADSHOTS_FILENAME)
