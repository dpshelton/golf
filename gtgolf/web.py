"""Flask pages for the home screen, standings, and tournament lists.

Templates and static files stay at the repository root so the existing
``templates/`` and ``static/`` directories do not move.
"""

from pathlib import Path

from flask import Flask, render_template

from gtgolf import config, db, profiles, tee_times

_ROOT = Path(__file__).resolve().parents[1]
app = Flask(
    __name__,
    template_folder=str(_ROOT / 'templates'),
    static_folder=str(_ROOT / 'static'),
)


def index_standings(leaderboard):
    """Map integer player id to the first leaderboard row with that id.

    Args:
        leaderboard: Annotated leaderboard rows.

    Returns:
        Dict used for pick lookups.
    """
    standings = {}
    for player in leaderboard:
        standings.setdefault(int(player['PlayerID']), player)
    return standings


def get_player_standing(player_id, leaderboard):
    """Return the leaderboard row for ``player_id``.

    Args:
        player_id: SportsData id. Numeric strings and ints match.
        leaderboard: A list of rows, or the dict from ``index_standings``.

    Returns:
        The first matching row, or None.
    """
    if isinstance(leaderboard, dict):
        return leaderboard.get(int(player_id))
    for player in leaderboard:
        if int(player_id) == int(player['PlayerID']):
            return player
    return None


def _headshot_urls(headshots):
    """Map player id to the first preferred headshot URL.

    Args:
        headshots: Headshot mappings.

    Returns:
        Dict of ``PlayerID`` to URL. A stored null URL is kept.
    """
    urls = {}
    for headshot in headshots:
        urls.setdefault(headshot['PlayerID'], headshot['PreferredHostedHeadshotUrl'])
    return urls


def _pick_view(profile, standing, pick, photo_url):
    """Build one results-table row for an owner pick.

    Args:
        profile: Player profile.
        standing: Annotated leaderboard row.
        pick: Pick row.
        photo_url: Headshot or profile photo.

    Returns:
        Template mapping.
    """
    return {
        'DraftKingsName': profile['DraftKingsName'],
        'Rank': standing['Rank'],
        'Points': standing['Points'],
        'OneAndDonePoints': standing['OneAndDonePoints'],
        'PhotoUrl': photo_url,
        'OneAndDone': pick['OneAndDone'],
        'TotalThrough': standing['TotalThrough'],
        'TeeTime': standing['TeeTime'],
        'SecondsSinceTeeTime': standing['SecondsSinceTeeTime'],
    }


@app.route('/')
def index():
    """Render the home page.

    Returns:
        HTML response.
    """
    return render_template('index.html')


@app.route('/results')
def results():
    """Render live pool standings for ``TOURNAMENT_ID``.

    Returns:
        HTML response, or a 404 tuple when that tournament is not in SQLite.
    """
    tournament_id = config.TOURNAMENT_ID
    tournament = db.get_tournament_from_id(tournament_id)
    if tournament is None:
        return 'Tournament not found', 404

    leaderboard, last_updated = db.get_leaderboard(tournament_id)
    last_updated_str, total_seconds = tee_times.get_last_updated_str(last_updated)
    leaderboard = tee_times.annotate_leaderboard(leaderboard)
    standings = index_standings(leaderboard)
    player_profiles = profiles.load_player_profiles()
    headshot_urls = _headshot_urls(profiles.load_headshots())
    picks = db.get_picks(tournament_id)

    edited_picks = {}
    totals = {}
    for owner in config.OWNERS:
        edited_picks[owner] = []
        totals[owner] = 0
        for pick in picks[owner]:
            profile = profiles.get_player_profile(player_id=pick['PlayerID'], player_profiles=player_profiles)
            # Natalie is not in the SportsData feed. She scores nothing and
            # uses a picture shipped under static/ when that file is present.
            if profile['DraftKingsName'] == 'Natalie Shelton':
                totals[owner] += 0
                edited_picks[owner].append({
                    'DraftKingsName': profile['DraftKingsName'],
                    'Rank': None,
                    'Points': 0,
                    'OneAndDonePoints': 0,
                    'PhotoUrl': '/static/natalie.jpg',
                    'OneAndDone': pick['OneAndDone'],
                    'TotalThrough': 'None',
                    'TeeTime': 'None',
                    'SecondsSinceTeeTime': 'None',
                })
                continue

            standing = standings.get(int(pick['PlayerID']))
            if standing is None:
                print('Failed to find {} ({}) in leaderboard'.format(profile['DraftKingsName'], pick['PlayerID']))
                continue

            if pick['OneAndDone']:
                totals[owner] += int(standing['OneAndDonePoints'])
            else:
                totals[owner] += int(standing['Points'])

            photo_url = headshot_urls.get(pick['PlayerID'], profile['PhotoUrl'])
            edited_picks[owner].append(_pick_view(profile, standing, pick, photo_url))

    # Higher scores first. sorted() is stable, so a tie stays in OWNERS order.
    totals = dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))
    return render_template(
        'results.html',
        leaderboard=leaderboard,
        picks=edited_picks,
        totals=totals,
        owners=config.OWNERS,
        last_updated=last_updated_str,
        total_seconds=total_seconds,
        tournament=tournament,
    )


@app.route('/tournaments')
def tournaments():
    """Render active, upcoming, and past tournaments.

    Returns:
        HTML response.
    """
    active_tournaments, upcoming_tournaments, past_tournaments, _relevant = db.get_tournaments()
    return render_template(
        'tournaments.html',
        active_tournaments=active_tournaments,
        upcoming_tournaments=upcoming_tournaments,
        past_tournaments=past_tournaments,
    )
