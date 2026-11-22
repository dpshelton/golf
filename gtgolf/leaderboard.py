"""Live leaderboard polling.

This module sleeps between SportsData refreshes. Database writes themselves
live in ``gtgolf.db``.
"""

import time
from datetime import datetime

from gtgolf import api, config, db, profiles, tee_times


def update_picks():
    """Drop the picks table and insert the lineups in ``PICKS``."""
    print('Updating picks...')
    db.create_picks_table()
    db.add_picks()


def wait_for_round_start(leaderboard, round_num, do_update_picks):
    """Block until ``round_num`` tees off, then optionally rebuild picks.

    Args:
        leaderboard: Raw API leaderboard.
        round_num: 1-based round number.
        do_update_picks: When True, replace picks after the wait. This is how
            round 1 locks the hand-entered lineups once tee times are real.
    """
    first_tee_time = tee_times.get_first_tee_time(leaderboard, round_num)
    if first_tee_time is None:
        print('Tee times are not posted for round {}!'.format(round_num))
        return

    now = datetime.now()
    if now < first_tee_time:
        sleep_seconds = int((first_tee_time - now).total_seconds())
        print('Now: {}, First Tee Time: {}. Sleeping for {} seconds...'.format(
            now.strftime('%Y-%m-%d %H:%M:%S'),
            first_tee_time,
            sleep_seconds,
        ))
        time.sleep(sleep_seconds)

    # Picks are locked in only after a round actually has tee times. A round
    # with an empty tee sheet used to skip this, and still does.
    if do_update_picks:
        update_picks()


def manage_leaderboard(tournament_id, starting_round_num=1):
    """Poll the leaderboard from one round through the end of the event.

    Sleeps until the first tee time, then refreshes every
    ``LEADERBOARD_UPDATE_PERIOD`` seconds. After the last tee time has passed
    and no golfer still has a ``TotalThrough`` value, the round is over and
    the loop sleeps ``ROUND_END_SLEEP_PERIOD`` before the next round.

    A non-null ``TotalThrough`` means the golfer is still on the course. The
    feed clears that field instead of sending ``F`` when the round ends.

    Profiles are downloaded once at the start. Headshots are not: that
    endpoint rejected a second pull after one successful fetch, so
    ``headshots.json`` stays a saved snapshot. Picks are rebuilt only when
    this run starts at round 1, and only once the first tee time arrives.

    Args:
        tournament_id: SportsData tournament id.
        starting_round_num: 1-based round to begin with.
    """
    round_num = starting_round_num
    first_iteration = True
    profiles.fetch_player_profiles()
    leaderboard = api.api_get_leaderboard(tournament_id)
    num_rounds = len(leaderboard['Tournament']['Rounds'])

    while round_num <= num_rounds:
        if not first_iteration:
            leaderboard = api.api_get_leaderboard(tournament_id)
        db.update_leaderboard(tournament_id, leaderboard)
        wait_for_round_start(
            leaderboard,
            round_num,
            do_update_picks=first_iteration and starting_round_num == 1,
        )

        round_complete = True
        last_tee_time = tee_times.get_last_tee_time(leaderboard, round_num)
        now = datetime.now()
        if last_tee_time is not None and last_tee_time > now:
            print('Now: {}, Last Tee Time: {}. Last tee time not reached.'.format(
                now.strftime('%Y-%m-%d %H:%M:%S'),
                last_tee_time,
            ))
            round_complete = False
        else:
            players_remaining = sum(
                1 for player in leaderboard['Players'] if player['TotalThrough'] is not None
            )
            if players_remaining > 0:
                print('Waiting for {} players to complete round.'.format(players_remaining))
                round_complete = False

        if round_complete:
            print('Round {} is over.'.format(round_num))
            round_num += 1
            print('Sleeping for {} seconds'.format(config.ROUND_END_SLEEP_PERIOD))
            time.sleep(config.ROUND_END_SLEEP_PERIOD)
        else:
            print('Sleeping for {} seconds'.format(config.LEADERBOARD_UPDATE_PERIOD))
            time.sleep(config.LEADERBOARD_UPDATE_PERIOD)

        first_iteration = False
