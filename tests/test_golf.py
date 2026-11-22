"""Behavior checks for the fantasy golf pool.

The bundled database is the January 2024 Farmers Insurance Open. Tests that
read it copy the file first so the real ``database.db`` is left alone.
Finished-round markers (``F``) depend on the clock being after that event.
"""

import hashlib
import os
import random
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

import golf  # noqa: E402


def _oracle_points(rank, one_n_done=False, major=False):
    """Original band walk, used to prove the lookup table did not drift."""
    multiplier = golf.MAJOR_MULTIPLIER if major else 1
    if rank is None:
        return 0
    table = golf.ONE_N_DONE_POINTS if one_n_done else golf.POINTS
    for start, end, points in table:
        if rank >= start and rank <= end:
            return points * multiplier
    return 0


class ScoringTests(unittest.TestCase):
    def test_known_places(self):
        self.assertEqual(golf.get_points(None), 0)
        self.assertEqual(golf.get_points(0), 0)
        self.assertEqual(golf.get_points(1), 150)
        self.assertEqual(golf.get_points(2), 75)
        self.assertEqual(golf.get_points(10), 14)
        self.assertEqual(golf.get_points(11), 12)
        self.assertEqual(golf.get_points(15), 12)
        self.assertEqual(golf.get_points(16), 10)
        self.assertEqual(golf.get_points(61), 3)
        self.assertEqual(golf.get_points(1000), 3)
        self.assertEqual(golf.get_points(1001), 0)
        self.assertEqual(golf.get_points(1, one_n_done=True), 50)
        self.assertEqual(golf.get_points(10, one_n_done=True), 3)
        self.assertEqual(golf.get_points(11, one_n_done=True), 0)
        self.assertEqual(golf.get_points(1, major=True), 300)
        self.assertEqual(golf.get_points(1, one_n_done=True, major=True), 100)

    def test_non_integer_ranks_follow_the_bands(self):
        # True compares equal to 1, so it historically scores a win.
        self.assertEqual(golf.get_points(True), 150)
        self.assertEqual(golf.get_points(False), 0)
        self.assertEqual(golf.get_points(1.0), 150)
        self.assertEqual(golf.get_points(1.5), 0)

    def test_lookup_matches_every_band(self):
        ranks = list(range(0, 1002)) + [None, True, False, 1.0, 1.5, 11.0]
        for rank in ranks:
            for one_n_done in (False, True):
                for major in (False, True):
                    self.assertEqual(
                        golf.get_points(rank, one_n_done=one_n_done, major=major),
                        _oracle_points(rank, one_n_done, major),
                    )


class LeaderboardParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = golf.load_player_profiles()

    def test_ties_and_unranked_order(self):
        leaderboard = {
            'Players': [
                {'PlayerID': 40000020, 'TotalScore': -8, 'TotalThrough': 14, 'TeeTime': '2024-01-25T11:50:00'},
                {'PlayerID': 40004956, 'TotalScore': -8, 'TotalThrough': 18, 'TeeTime': '2024-01-25T12:00:00'},
                {'PlayerID': 40005167, 'TotalScore': -7, 'TotalThrough': None, 'TeeTime': None},
                {'PlayerID': 40004432, 'TotalScore': None, 'TotalThrough': None, 'TeeTime': '2024-01-25T15:00:00'},
                {'PlayerID': 40004123, 'TotalScore': -7, 'TotalThrough': 9, 'TeeTime': '2024-01-25T13:00:00'},
            ]
        }
        parsed = golf.parse_leaderboard(leaderboard, self.profiles)
        self.assertEqual(
            [(row['DraftKingsName'], row['Rank'], row['Points'], row['OneAndDonePoints'], row['TotalThrough'], row['TeeTime']) for row in parsed],
            [
                ('Jamie Abbott', '1', '150', '50', 14, '2024-01-25T11:50:00'),
                ('Alyaa Abdulghany', '1', '150', '50', 18, '2024-01-25T12:00:00'),
                ('Lakareber Abe', '3', '50', '15', 'None', 'None'),
                ('Blake Abercrombie', '3', '50', '15', 9, '2024-01-25T13:00:00'),
                ('John Aber', 'None', '0', '0', 'None', '2024-01-25T15:00:00'),
            ],
        )

    def test_duplicate_names_keep_the_first_profile(self):
        self.assertEqual(golf.get_player_id_from_name('Jamal Hossain', self.profiles), 40005516)
        self.assertEqual(golf.get_player_id_from_name('Seonghyeon Kim', self.profiles), 40003586)
        self.assertIsNone(golf.get_player_id_from_name('Nobody Real', self.profiles))

    def test_either_id_uses_file_order(self):
        # Jamie Abbott (DraftKings 471720) appears before Lakareber Abe, so the
        # DraftKings id wins even though a later row matches the player id.
        profile = golf.get_player_profile(
            player_id=40005167,
            draft_kings_player_id=471720,
            player_profiles=self.profiles,
        )
        self.assertEqual(profile['PlayerID'], 40000020)
        self.assertEqual(
            golf.get_player_profile(player_id=40003252, player_profiles=self.profiles)['DraftKingsName'],
            'Ludvig Aberg',
        )

    def test_profiles_are_cached_until_the_file_changes(self):
        self.assertIs(golf.load_player_profiles(), golf.load_player_profiles())


class TeeTimeTests(unittest.TestCase):
    def test_eastern_times_shift_three_hours(self):
        converted = golf.convert_tee_time('2024-01-25T11:50:00')
        self.assertEqual(converted, datetime(2024, 1, 25, 8, 50))
        self.assertEqual(golf.get_time_str(converted), '8:50AM')
        self.assertEqual(golf.convert_tee_time('2024-01-25T00:05:00'), datetime(2024, 1, 24, 21, 5))
        self.assertEqual(golf.get_time_str(golf.convert_tee_time('2024-01-25T00:05:00')), '9:05PM')
        self.assertIsNone(golf.convert_tee_time(None))
        self.assertEqual(golf.convert_tee_time('None'), 'None')
        self.assertEqual(golf.get_time_str(None), 'None')
        self.assertEqual(golf.get_time_str('None'), 'None')
        # Strings that skip convert_tee_time are formatted as written.
        self.assertEqual(golf.get_time_str('2024-01-25T00:05:00'), '12:05AM')
        self.assertEqual(golf.get_time_str(golf.convert_tee_time(datetime(2024, 1, 25, 15, 0))), '12:00PM')

    def test_first_and_last_tee_times(self):
        leaderboard = {
            'Players': [
                {'Rounds': [{'TeeTime': '2024-01-25T12:00:00'}, {'TeeTime': None}]},
                {'Rounds': [{'TeeTime': '2024-01-25T08:10:00'}]},
                {'Rounds': []},
                {'Rounds': [{'TeeTime': '2024-01-25T09:00:00'}]},
            ]
        }
        self.assertEqual(golf.get_first_tee_time(leaderboard, 1), datetime(2024, 1, 25, 5, 10))
        self.assertEqual(golf.get_last_tee_time(leaderboard, 1), datetime(2024, 1, 25, 9, 0))
        self.assertIsNone(golf.get_first_tee_time(leaderboard, 2))
        self.assertIsNone(golf.get_last_tee_time(leaderboard, 2))
        self.assertIsNone(golf.get_first_tee_time(leaderboard, 3))

    def test_last_updated_text(self):
        real_datetime = golf.datetime

        class Frozen(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2024, 1, 25, 9, 21, 25)

        with mock.patch('golf.datetime', Frozen):
            text, seconds = golf.get_last_updated_str({'LeaderboardLastUpdated': '2024-01-25 08:20:20'})
        self.assertEqual(text, 'Updated 1h 1m 5s ago')
        self.assertEqual(seconds, 3665)

        class FrozenMinutes(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2024, 1, 25, 8, 21, 25)

        with mock.patch('golf.datetime', FrozenMinutes):
            text, seconds = golf.get_last_updated_str({'LeaderboardLastUpdated': '2024-01-25 08:20:20'})
        self.assertEqual(text, 'Updated 1m 5s ago')
        self.assertEqual(seconds, 65)

        class FrozenSeconds(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2024, 1, 25, 8, 20, 30)

        with mock.patch('golf.datetime', FrozenSeconds):
            text, seconds = golf.get_last_updated_str({'LeaderboardLastUpdated': '2024-01-25 08:20:20'})
        self.assertEqual(text, 'Updated 10s ago')
        self.assertEqual(seconds, 10)


class RosterTests(unittest.TestCase):
    def test_printed_lineup_matches_the_historical_format(self):
        roster = golf.Roster([
            {'DraftKingsName': 'B', 'FantasyPoints': 8, 'DraftKingsSalary': 7000, 'Value': 1142.857},
            {'DraftKingsName': 'A', 'FantasyPoints': 10.5, 'DraftKingsSalary': 9000, 'Value': 1166.666},
        ])
        self.assertEqual(
            str(roster),
            'Points: 18.500, Salary: 16000\n'
            '    A                             , Points: 10.500, Salary:  9000, Value: 1166.666\n'
            '    B                             , Points: 8.000, Salary:  7000, Value: 1142.857\n',
        )
        self.assertEqual([player['DraftKingsName'] for player in roster.players], ['A', 'B'])

    def test_same_salary_upgrade_and_tie_keep(self):
        players = [
            {'DraftKingsName': 'A', 'DraftKingsSalary': 9000, 'FantasyPoints': 10, 'Value': 10},
            {'DraftKingsName': 'B', 'DraftKingsSalary': 9000, 'FantasyPoints': 30, 'Value': 30},
            {'DraftKingsName': 'C', 'DraftKingsSalary': 9000, 'FantasyPoints': 5, 'Value': 5},
            {'DraftKingsName': 'D', 'DraftKingsSalary': 8000, 'FantasyPoints': 4, 'Value': 4},
            {'DraftKingsName': 'E', 'DraftKingsSalary': 8000, 'FantasyPoints': 9, 'Value': 9},
        ]
        with mock.patch.object(golf, 'get_starting_roster', return_value=[players[0], players[2]]):
            with mock.patch('sys.stdout', StringIO()):
                roster = golf.get_roster(players)
        # A upgrades to B. C is not upgraded to B because B was just taken, and
        # A's value is higher than C's, so A replaces C.
        self.assertEqual([player['DraftKingsName'] for player in roster.players], ['B', 'A'])

        tied = [
            {'DraftKingsName': 'A', 'DraftKingsSalary': 9000, 'FantasyPoints': 10, 'Value': 10},
            {'DraftKingsName': 'B', 'DraftKingsSalary': 9000, 'FantasyPoints': 10, 'Value': 10},
        ]
        with mock.patch.object(golf, 'get_starting_roster', return_value=[tied[0]]):
            with mock.patch('sys.stdout', StringIO()):
                roster = golf.get_roster(tied)
        self.assertEqual(roster.players[0]['DraftKingsName'], 'A')

    def test_random_search_follows_the_salary_cap_rule(self):
        players = [
            {
                'DraftKingsName': 'P{}'.format(i),
                'DraftKingsSalary': 6000 + (i * 100),
                'FantasyPoints': float(i + 1),
                'Value': float(i + 1),
            }
            for i in range(12)
        ]

        def oracle(attempts):
            best_points = 0
            best = None
            for _ in range(attempts):
                selected = random.sample(players, golf.NUM_PICKS)
                total_points = sum(player['FantasyPoints'] for player in selected)
                total_salary = sum(player['DraftKingsSalary'] for player in selected)
                if total_salary <= golf.MAX_SALARY and total_points > best_points:
                    best_points = total_points
                    best = selected
            return [player['DraftKingsName'] for player in best]

        random.seed(7)
        with mock.patch('sys.stdout', StringIO()):
            chosen = golf.get_starting_roster(players, attempts=40)
        random.seed(7)
        self.assertEqual([player['DraftKingsName'] for player in chosen], oracle(40))
        self.assertEqual(golf.get_starting_roster.__defaults__, (1000000,))


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'database.db')
        shutil.copy(ROOT / 'database.db', self.db_path)
        self.previous_database = golf.DATABASE
        golf.DATABASE = self.db_path

    def tearDown(self):
        golf.DATABASE = self.previous_database
        self.tmp.cleanup()

class DatabaseTests(DatabaseCase):
    def test_saved_leaderboard_and_picks(self):
        leaderboard, updated = golf.get_leaderboard(585)
        self.assertEqual(len(leaderboard), 160)
        self.assertEqual(dict(updated)['LeaderboardLastUpdated'], '2024-01-25 08:20:20')
        self.assertEqual(dict(leaderboard[0])['DraftKingsName'], 'Kevin Yu')
        self.assertEqual(dict(leaderboard[0])['Points'], '150')
        picks = golf.get_picks(585)
        self.assertEqual(
            [row['PlayerID'] for row in picks['Ben']],
            [40000638, 40000314, 40002925, 40004729, 40000869, 40000632],
        )
        self.assertEqual(
            [row['PlayerID'] for row in picks['Don']],
            [40000216, 40000540, 40001211, 40000115, 40001686, 40002471],
        )
        tournament = golf.get_tournament_from_id(585)
        self.assertEqual(tournament['Name'], 'Farmers Insurance Open')
        self.assertIsNone(golf.get_tournament_from_id(999999))

    def test_indexes_are_created_without_changing_rows(self):
        before = sqlite3.connect(self.db_path).execute('SELECT COUNT(*) FROM leaderboards').fetchone()[0]
        golf.get_db_connection().close()
        connection = sqlite3.connect(self.db_path)
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        after = connection.execute('SELECT COUNT(*) FROM leaderboards').fetchone()[0]
        connection.close()
        self.assertIn('idx_leaderboards_tournament_player', names)
        self.assertIn('idx_salaries_tournament', names)
        self.assertIn('idx_picks_owner_tournament', names)
        self.assertEqual(before, after)

    def test_tournament_windows(self):
        connection = sqlite3.connect(self.db_path)
        now = datetime.now()

        def insert(start_delta, end_delta, tournament_id, name):
            start = (now + golf.timedelta(days=start_delta)).strftime('%Y-%m-%dT00:00:00')
            end = (now + golf.timedelta(days=end_delta)).strftime('%Y-%m-%dT00:00:00')
            connection.execute(
                'INSERT INTO tournaments (TournamentID, Name, StartDate, EndDate, Location, Venue) VALUES (?, ?, ?, ?, ?, ?)',
                (tournament_id, name, start, end, 'Test City', 'Test Course'),
            )

        insert(-1, 1, 9001, 'ACTIVE TEST')
        insert(2, 4, 9002, 'UPCOMING TEST')
        insert(-10, -3, 9003, 'PAST TEST')
        insert(-1, 10, 9004, 'RELEVANT TEST')
        connection.commit()
        connection.close()

        active, upcoming, past, relevant = golf.get_tournaments()
        self.assertIn(9001, {row['TournamentID'] for row in active})
        self.assertNotIn(9002, {row['TournamentID'] for row in active})
        self.assertIn(9002, {row['TournamentID'] for row in upcoming})
        self.assertIn(9003, {row['TournamentID'] for row in past})
        self.assertNotIn(9001, {row['TournamentID'] for row in past})
        self.assertIn(9004, {row['TournamentID'] for row in relevant})

    def test_update_leaderboard_inserts_then_updates_in_place(self):
        with golf.db_connection() as connection:
            connection.execute(
                'INSERT INTO tournaments (TournamentID, Name, StartDate, EndDate) VALUES (?, ?, ?, ?)',
                (424242, 'Unit Test Open', '2024-01-01T00:00:00', '2024-01-04T00:00:00'),
            )
            connection.commit()

        leaderboard = {
            'Players': [
                {'PlayerID': 40000638, 'TotalScore': -5, 'TotalThrough': 12, 'TeeTime': '2024-01-25T11:50:00'},
                {'PlayerID': 40004412, 'TotalScore': -5, 'TotalThrough': None, 'TeeTime': None},
                {'PlayerID': 40000314, 'TotalScore': None, 'TotalThrough': None, 'TeeTime': None},
            ]
        }
        golf.update_leaderboard(424242, leaderboard)
        with golf.db_connection() as connection:
            rows = connection.execute(
                'SELECT * FROM leaderboards WHERE TournamentID == ? ORDER BY Position',
                (424242,),
            ).fetchall()
            stamp = connection.execute(
                'SELECT LeaderboardLastUpdated FROM tournaments WHERE TournamentID == ?',
                (424242,),
            ).fetchone()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['DraftKingsName'], 'Max Homa')
        self.assertEqual(rows[0]['Rank'], '1')
        self.assertEqual(rows[0]['Points'], '150')
        self.assertEqual(rows[1]['DraftKingsName'], 'Unknown')
        self.assertEqual(rows[1]['DraftKingsPlayerID'], 'Unknown')
        self.assertEqual(rows[1]['Rank'], '1')
        self.assertEqual(rows[2]['Rank'], 'None')
        self.assertEqual(rows[2]['Points'], '0')
        self.assertIsNotNone(stamp['LeaderboardLastUpdated'])

        leaderboard['Players'][0]['TotalScore'] = -1
        leaderboard['Players'][1]['TotalScore'] = -4
        reordered = {
            'Players': [
                leaderboard['Players'][1],
                leaderboard['Players'][0],
                leaderboard['Players'][2],
            ]
        }
        golf.update_leaderboard(424242, reordered)
        with golf.db_connection() as connection:
            rows = connection.execute(
                'SELECT PlayerID, Rank, Points, DraftKingsName, Position FROM leaderboards WHERE TournamentID == ? ORDER BY Position',
                (424242,),
            ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['PlayerID'], '40004412')
        self.assertEqual(rows[0]['Rank'], '1')
        self.assertEqual(rows[0]['Points'], '150')
        self.assertEqual(rows[0]['DraftKingsName'], 'Unknown')
        self.assertEqual(rows[1]['PlayerID'], '40000638')
        self.assertEqual(rows[1]['Rank'], '2')
        self.assertEqual(rows[1]['Points'], '75')
        self.assertEqual(rows[1]['DraftKingsName'], 'Max Homa')

    def test_add_pick_resolves_names(self):
        golf.create_picks_table()
        with mock.patch('sys.stdout', StringIO()):
            golf.add_pick('Ben', 585, 'Max Homa')
            golf.add_pick('Ben', 585, 'Not A Golfer')
        with golf.db_connection() as connection:
            rows = connection.execute('SELECT Owner, PlayerID, OneAndDone FROM picks').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['PlayerID'], 40000638)
        self.assertEqual(rows[0]['OneAndDone'], 0)

    def test_results_standings_match_the_saved_pool(self):
        with mock.patch('sys.stdout', StringIO()) as stdout:
            with mock.patch('golf.render_template', side_effect=lambda template, **kwargs: (template, kwargs)):
                template, kwargs = golf.results()
        self.assertNotIn('PreferredHostedHeadshotUrl', stdout.getvalue())
        self.assertEqual(template, 'results.html')
        self.assertEqual(kwargs['totals'], {'Don': 118, 'Mike': 42, 'Greg': 28, 'Sean': 27, 'Ben': 24})
        self.assertEqual(kwargs['tournament']['Name'], 'Farmers Insurance Open')
        ben = kwargs['picks']['Ben']
        self.assertEqual(
            [player['DraftKingsName'] for player in ben],
            ['Max Homa', 'Jason Day', 'Min Woo Lee', 'Sam Stevens', 'Luke List', 'Charley Hoffman'],
        )
        self.assertEqual(ben[0]['TeeTime'], '9:23AM')
        self.assertEqual(ben[0]['TotalThrough'], 'F')
        self.assertEqual(ben[0]['Points'], '5')
        self.assertTrue(ben[2]['PhotoUrl'].endswith('/headshots/golf/low-res/0.png'))
        stable = [
            (
                player['PlayerID'],
                player['Rank'],
                player['DraftKingsName'],
                player['Points'],
                player['OneAndDonePoints'],
                player['TotalThrough'],
                player['TeeTime'],
            )
            for player in kwargs['leaderboard']
        ]
        digest = hashlib.sha256(repr(stable).encode()).hexdigest()
        self.assertEqual(digest, '93014abf6afa1045a4d1aea523b83a12053da251d96e8cc8379684f758e3ceeb')
        self.assertEqual(stable[0][2:], ('Kevin Yu', '150', '50', 'F', '8:50AM'))

    def test_missing_tournament_results_are_a_404(self):
        with mock.patch.object(golf, 'TOURNAMENT_ID', 999999):
            self.assertEqual(golf.results(), ('Tournament not found', 404))

    def test_salary_values_do_not_call_the_network(self):
        with mock.patch.object(golf, 'api_request', side_effect=AssertionError('network')):
            players = golf.get_players(546)
            self.assertEqual(len(players), 163)
            for player in players:
                expected = 1e6 * (float(player['FantasyPoints']) / float(player['DraftKingsSalary']))
                self.assertAlmostEqual(player['Value'], expected)
            best_value = max(players, key=lambda player: player['Value'])
            best_points = max(players, key=lambda player: player['FantasyPoints'])
            worst_value = min(players, key=lambda player: player['Value'])
            worst_points = min(players, key=lambda player: player['FantasyPoints'])
            with mock.patch('sys.stdout', StringIO()) as stdout:
                golf.values(546)
            value_text = stdout.getvalue()
            self.assertLess(
                value_text.index(best_value['DraftKingsName']),
                value_text.index(worst_value['DraftKingsName']),
            )
            with mock.patch('sys.stdout', StringIO()) as stdout:
                golf.points(546)
            points_text = stdout.getvalue()
            self.assertLess(
                points_text.index(best_points['DraftKingsName']),
                points_text.index(worst_points['DraftKingsName']),
            )


class WebTests(DatabaseCase):
    def test_pages_render_the_saved_pool(self):
        golf.app.config['TESTING'] = True
        client = golf.app.test_client()
        home = client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'Welcome to GTGolf', home.data)
        self.assertIn(b'GT Golf Club', home.data)

        tournaments = client.get('/tournaments')
        self.assertEqual(tournaments.status_code, 200)
        self.assertIn(b'Active Tournaments', tournaments.data)
        self.assertIn(b'Upcoming Tournaments', tournaments.data)
        self.assertIn(b'Past Tournaments', tournaments.data)

        results = client.get('/results')
        self.assertEqual(results.status_code, 200)
        self.assertIn(b'Farmers Insurance Open', results.data)
        self.assertIn(b'Torrey Pines', results.data)
        for owner in (b'Ben', b'Greg', b'Mike', b'Don', b'Sean'):
            self.assertIn(owner, results.data)
        self.assertIn(b'118', results.data)
        self.assertIn(b'Max Homa', results.data)
        self.assertIn(b'Kevin Yu', results.data)


class CommandLineTests(unittest.TestCase):
    def test_flags(self):
        with mock.patch('sys.argv', ['golf.py', 'autopick', '-n', '2', '-r', '3']):
            args = golf.parse_args()
        self.assertEqual(args.cmd, 'autopick')
        self.assertEqual(args.num_rosters, 2)
        self.assertEqual(args.round_num, 3)

    def test_unknown_command_is_rejected(self):
        with mock.patch('sys.argv', ['golf.py', 'not-a-command']):
            with self.assertRaises(SystemExit):
                golf.parse_args()


if __name__ == '__main__':
    unittest.main()
