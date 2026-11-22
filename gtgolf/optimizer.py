"""DraftKings salary-cap search.

Value is projected fantasy points per million dollars of salary. ``autopick``
samples ``NUM_PICKS`` golfers at random, keeps the best legal lineup, then
swaps a starter for a strictly better value at the same salary.
"""

import random
import sys

from prettytable import PrettyTable

from gtgolf import config, db, profiles


class Roster:
    """A lineup plus its projected fantasy points and DraftKings salary.

    Players are kept highest salary first so the printed form is stable.
    """

    def __init__(self, players):
        """Store ``players`` sorted by salary and cache the two totals.

        Args:
            players: Mappings with ``FantasyPoints``, ``DraftKingsSalary``,
                ``DraftKingsName``, and ``Value``.
        """
        self.players = sorted(players, key=lambda player: player['DraftKingsSalary'], reverse=True)
        self.total_points = self.get_total_points()
        self.total_salary = self.get_total_salary()

    def get_total_points(self):
        """Return the sum of projected fantasy points.

        Returns:
            Numeric total, or 0 for an empty lineup.
        """
        return sum(player['FantasyPoints'] for player in self.players)

    def get_total_salary(self):
        """Return the sum of DraftKings salaries.

        Returns:
            Integer salary total, or 0 for an empty lineup.
        """
        return sum(player['DraftKingsSalary'] for player in self.players)

    def __str__(self):
        """Return the multi-line lineup used by ``autopick``."""
        lines = [
            'Points: {:.3f}, Salary: {:5}'.format(self.total_points, self.total_salary),
        ]
        for player in self.players:
            lines.append('    {:30}, Points: {:.3f}, Salary: {:5}, Value: {:.3f}'.format(
                player['DraftKingsName'],
                player['FantasyPoints'],
                player['DraftKingsSalary'],
                player['Value'],
            ))
        return '\n'.join(lines) + '\n'


def get_players(tournament_id):
    """Build salary-cap candidates from stored salaries and projections.

    Args:
        tournament_id: SportsData tournament id.

    Returns:
        List of mappings with name, salary, fantasy points, and value.
        Value is projected points per million dollars of salary. Golfers
        without a salary are omitted.
    """
    by_id = profiles._profile_indexes(profiles.load_player_profiles())['by_player_id']
    players = []
    for salary in db.get_salaries(tournament_id):
        if salary['DraftKingsSalary'] is None:
            continue
        # A missing profile still raises TypeError on the subscript below.
        profile = by_id.get(salary['PlayerID'])
        fantasy_points = salary['FantasyPoints']
        draft_salary = salary['DraftKingsSalary']
        players.append({
            'DraftKingsName': profile['DraftKingsName'],
            'DraftKingsSalary': draft_salary,
            'FantasyPoints': fantasy_points,
            'Value': 1e6 * (float(fantasy_points) / float(draft_salary)),
        })
    return players


def get_starting_roster(players, attempts=1000000):
    """Sample random legal lineups and keep the highest projected score.

    Args:
        players: Candidates from ``get_players``.
        attempts: How many random ``NUM_PICKS`` lineups to try. The command
            line uses one million, which is the historical search size.

    Returns:
        The best lineup found, as the original player dicts, or None when
        every sample was over ``MAX_SALARY``.
    """
    max_fantasy_points = 0
    max_players = None
    for i in range(attempts):
        sys.stdout.write('{}\r'.format(i))
        sys.stdout.flush()

        selected_players = random.sample(players, config.NUM_PICKS)
        total_fantasy_points = sum(player['FantasyPoints'] for player in selected_players)
        total_salary = sum(player['DraftKingsSalary'] for player in selected_players)
        if total_salary <= config.MAX_SALARY and total_fantasy_points > max_fantasy_points:
            max_fantasy_points = total_fantasy_points
            max_players = selected_players
            print('\nTotal Salary: {:5}, Fantasy Points: {:0.3f}, Players: {}'.format(
                total_salary,
                total_fantasy_points,
                ', '.join(player['DraftKingsName'] for player in selected_players),
            ))
    return max_players


def get_roster(players):
    """Improve a random lineup by swapping in better value at the same salary.

    Each starter is compared with other golfers who cost the same. A golfer
    already chosen, or the starter themself, is not a prospect. The swap
    happens only when the best prospect's value is strictly higher.

    Args:
        players: Candidates from ``get_players``.

    Returns:
        ``Roster`` for the upgraded lineup.
    """
    starting_roster = get_starting_roster(players)

    print()
    print()
    print('Starting Roster')
    for player in starting_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(
            player['DraftKingsName'],
            player['DraftKingsSalary'],
            player['Value'],
        ))
    print('Points: {:.3f}'.format(sum(player['FantasyPoints'] for player in starting_roster)))
    print('Salary: {:5}'.format(sum(player['DraftKingsSalary'] for player in starting_roster)))
    print()

    by_salary = {}
    for prospect in players:
        by_salary.setdefault(prospect['DraftKingsSalary'], []).append(prospect)

    final_roster = []
    for player in starting_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(
            player['DraftKingsName'],
            player['DraftKingsSalary'],
            player['Value'],
        ))
        taken_names = {chosen['DraftKingsName'] for chosen in final_roster}
        prospects = [
            prospect
            for prospect in by_salary.get(player['DraftKingsSalary'], [])
            if prospect['DraftKingsName'] != player['DraftKingsName']
            and prospect['DraftKingsName'] not in taken_names
        ]
        prospects.sort(key=lambda prospect: prospect['Value'], reverse=True)
        for prospect in prospects:
            print('    Prospect: {}, Salary: {:5}, Value: {:.3f}'.format(
                prospect['DraftKingsName'],
                prospect['DraftKingsSalary'],
                prospect['Value'],
            ))

        if prospects and prospects[0]['Value'] > player['Value']:
            final_roster.append(prospects[0])
        else:
            final_roster.append(player)

    print()
    print('Final Roster')
    for player in final_roster:
        print('{:30}, Salary: {:5}, Value: {:.3f}'.format(
            player['DraftKingsName'],
            player['DraftKingsSalary'],
            player['Value'],
        ))
    print('Total Points: {:.3f}'.format(sum(player['FantasyPoints'] for player in final_roster)))
    print('Total Salary: {:5}'.format(sum(player['DraftKingsSalary'] for player in final_roster)))
    return Roster(final_roster)


def autopick(tournament_id, num_rosters):
    """Search ``num_rosters`` lineups and print them best-projected first.

    Args:
        tournament_id: SportsData tournament id.
        num_rosters: How many independent searches to run.
    """
    players = get_players(tournament_id)
    rosters = [get_roster(players) for _ in range(num_rosters)]
    rosters.sort(key=lambda roster: roster.total_points, reverse=True)

    print()
    print('*********************')
    print('*      ROSTERS      *')
    print('*********************')
    print()
    for roster in rosters:
        print(roster)


def _print_player_table(players):
    """Print the salary table shared by ``values`` and ``points``.

    Args:
        players: Already sorted candidate mappings.
    """
    table = PrettyTable()
    table.field_names = ['Player', 'FantasyPoints', 'Salary', 'Value']
    for player in players:
        table.add_row([
            player['DraftKingsName'],
            player['FantasyPoints'],
            player['DraftKingsSalary'],
            '{:.3f}'.format(player['Value']),
        ])
    print(table)


def values(tournament_id):
    """Print golfers sorted by points per million dollars of salary.

    Args:
        tournament_id: SportsData tournament id.
    """
    players = sorted(get_players(tournament_id), key=lambda player: player['Value'], reverse=True)
    _print_player_table(players)


def points(tournament_id):
    """Print golfers sorted by projected fantasy points.

    Args:
        tournament_id: SportsData tournament id.
    """
    players = sorted(get_players(tournament_id), key=lambda player: player['FantasyPoints'], reverse=True)
    _print_player_table(players)
