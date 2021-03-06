# -*- coding: utf-8 -*-
import json
import random
import warnings
import CONSTANTS
from model import *


class Lobby:
    def __init__(self, quiz, first_player, socket):
        print('Created new Lobby')
        self.players = []
        self.socket = socket
        self.quiz = quiz
        self.protocol = Protocol(self.quiz.get_id())
        self.add_player(first_player)

    def get_players(self):
        return self.players

    def set_players(self, players):
        self.players = players

    def add_player(self, player):
        print('Added Player ' + str(player.get_id()) + ' to lobby')
        self.players.append(player)
        self.protocol.add_player(player.get_id())
        self.protocol.put(player.get_id(), 'joined_lobby', self.quiz.get_id())
        if self.has_required_players():
            self.open_game()
        else:
            self.send_lobby_state_to_players()

    def remove_player(self, player):
        if player in self.players:
            self.players.remove(player)
            print('removed player ' + str(player.get_id()) + ' from lobby')
            self.send_lobby_state_to_players()

    def has_required_players(self):
        return len(self.players) >= self.quiz.get_min_participants()  # TODO when quiz model implemented: make this value generic

    def send_lobby_state_to_players(self):
        msg = json.dumps({'type': 'lobby',
                          'lobby': [player.get_id() for player in self.players],
                          'nicks': [player.get_nickname() for player in self.players]})

        self.notify_players(msg)

    def open_game(self):
        print('opening game for ' + str(len(self.players)) + ' players')
        GamePool.start_game(self.quiz, self.players, self.socket, self.protocol)
        self.close_lobby()

    def close_lobby(self):
        for id, lobby in list(LobbyPool.lobbies.items()):
            if lobby == self:
                del LobbyPool.lobbies[id]
                print("closed lobby")

    def notify_players(self, message):
        self.socket.notify_clients(message)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.get_players() == other.get_players()
        return False

    def __ne__(self, other):
        return self.get_players() != other.get_players()


class LobbyPool:
    lobbies = {}

    @staticmethod
    def join_lobby(player, socket, quiz_id=1):  # TODO update quiz_id when quiz model exists, for now leave this as 1!
        if quiz_id not in LobbyPool.lobbies:
            quiz = get_quiz(quiz_id)
            lobby = Lobby(quiz, player, socket)
            LobbyPool.lobbies[quiz_id] = lobby
        else:
            LobbyPool.lobbies[quiz_id].add_player(player)
        return quiz_id

    @staticmethod
    def get_lobby(quiz_id=1):
        return LobbyPool.lobbies[quiz_id]

    @staticmethod
    def leave_lobby(player, quiz_id=1):
        if LobbyPool.lobbies[quiz_id]:
            LobbyPool.lobbies[quiz_id].remove_player(player)
            if not LobbyPool.lobbies[quiz_id].get_players():
                del LobbyPool.lobbies[quiz_id]


class GamePool:
    games = {}

    @staticmethod
    def start_game(quiz, players, socket, protocol):
        for id in range(0, 1000):
            if id not in GamePool.games:
                game = Game(id, quiz, players, socket, protocol)
                GamePool.games[id] = game
                GamePool.games[id].start()
                break
        return id

    @staticmethod
    def get_game(game_id):
        return GamePool.games[game_id] if game_id in GamePool.games else None

    @staticmethod
    def remove_game(game_id):
        if game_id in GamePool.games:
            del GamePool.games[game_id]


class Game:
    def __init__(self, id, quiz, players, socket, protocol):
        self.id = id
        self.players = players
        self.quiz = quiz
        self.protocol = protocol
        self.waiting_players = set()

        self.played_questions = 0
        self.jackpot = Jackpot()
        self.player_ids = [player.get_id() for player in players]
        self.socket = socket
        self.scoreboard = {}
        self.item_table = ItemTable()
        for player_id in self.player_ids:
            self.scoreboard[player_id] = 0
        self.questions = self.quiz.get_random_questions()

    def get_id(self):
        return self.id

    def get_protocol(self):
        return self.protocol

    def get_players(self):
        return self.players

    def get_item_table(self):
        return self.item_table

    def get_waiting_players(self):
        return self.waiting_players

    def add_waiting_player(self, player_id, question_id):
        self.waiting_players.add(player_id)
        self.protocol.put(player_id, 'answered_question', question_id)
        self.check_for_next_question()

    def check_for_next_question(self):
        if self.all_players_answered():
            self.waiting_players.clear()
            self.start_next_question()

    def get_played_questions_amount(self):
        return self.played_questions

    def get_scoreboard(self):
        return self.scoreboard

    def start(self):
        msg = json.dumps({'type': 'game_start',
                          'game_id': self.id})
        self.notify_players(msg)
        for player_id in self.player_ids:
            self.protocol.put(player_id, 'joined_game', self.id)
        self.start_round()

    def start_round(self):
        self.start_next_question()

    def get_questions(self):
        return self.questions

    def get_questions_json(self):
        return [question.to_json() for question in self.questions]

    def get_jackpot(self):
        return self.jackpot

    def start_next_question(self):
        end_flag = False
        if self.played_questions == len(self.questions):
            self.end()
            end_flag = True
        elif self.played_questions == (len(self.questions) - 1):
            self.jackpot.set_active(True)
        else:
            self.jackpot.random_activation()

        if not end_flag:
            next_question = self.questions[self.played_questions].to_json()
            # assign an item (fixed probability to happen) to a random wrong answer
            next_question = self.assign_item_eventually(next_question)

            msg = json.dumps({'type': 'question',
                              'question': next_question,
                              'jackpot': {
                                            'amount': self.jackpot.get_amount(),
                                            'is_active': self.jackpot.get_is_active()},
                              'scoreboard': self.scoreboard
                              })
            self.notify_players(msg)
            for player_id in self.player_ids:
                self.protocol.put(player_id, 'got_question', next_question['id'])
        self.played_questions += 1

    def assign_item_eventually(self, next_question):
        chance = random.randint(1, 100)
        if chance <= CONSTANTS.ITEM_ASSIGNMENT_PROBABILITY:
            rand_index = random.randint(1, len(next_question['answers']) - 1)
            next_question['answers'][rand_index]['assigned_effects'] = Item().get_effect(self.scoreboard)
        return next_question

    def end(self):
        self.save_end_results()
        self.send_end_results()

    def send_end_results(self):
        msg = json.dumps({'type': 'scoreboard',
                          'scoreboard': self.scoreboard})
        self.notify_players(msg)
        for player_id in self.player_ids:
            self.protocol.put(player_id, 'got_scoreboard', True)
        self.log_protocol()

    def save_end_results(self):
        # TODO
        pass

    def log_protocol(self):
        """
        just for debugging
        """
        with open("protocol.json", "w", encoding="utf-8") as f:
            json.dump(self.protocol.table, f)

    def update_scoreboard(self, player_id, score):
        if player_id in self.scoreboard:
            self.scoreboard[player_id] += score

    def all_players_answered(self):
        return len(self.waiting_players) == len(self.players)

    def notify_players(self, message):
        self.socket.notify_clients(message)


class Jackpot:
    def __init__(self):
        self.inital_points = 1000
        self.initial_payout_chance = 10
        self.amount = self.inital_points
        self.payout_chance = self.initial_payout_chance
        self.payout_counter = 0
        self.is_active = False

    def get_initial_points(self):
        return self.inital_points

    def get_amount(self):
        return self.amount

    def set_amount(self, amount):
        self.amount = amount

    def get_payout_counter(self):
        return self.payout_counter

    def get_is_active(self):
        return self.is_active

    def set_active(self, bool_active):
        self.is_active = bool_active

    def get_payout_chance(self):
        return self.payout_chance

    def fill(self):
        """
        called after payout, fills jackpot with initial points
        """
        self.amount = self.inital_points

    def clear(self):
        """
        empties the jackpot
        """
        self.is_active = False
        self.amount = 0

    def payed_out(self):
        """
        called after payout, resets payout chance and refills initial inital points
        """
        self.clear()
        self.fill()
        self.payout_chance = self.initial_payout_chance
        self.payout_counter += 1

    def increase_payout_chance(self, value):
        """
        increase payout chance by value
        :param value: value to increase payout chance
        """
        self.payout_chance += value

    def random_activation(self):
        """
        randomly determine the jackpot activation
        """
        payout_threshold = 100 - self.payout_chance
        random_int = random.randint(0, 100) + 1
        if random_int >= payout_threshold:
            self.is_active = True

    def add_points(self, points):
        self.amount += points


class Item:
    def __init__(self):
        # dict with effect as key and initial impact value as value, all values tbd further
        # further possibilites: freeze other players,
        self.possible_effects = {
            'scoreX2': 0.3,
            'scoreX5': 0.7,
            'score/2': 0.5,
            'shuffle_question': 0.8,
            'jackpot': 1,
            'bomb': 0.6,
            'move_answers': 0.7,
            'hide_scoreboard': 0.1,
            'get_points_save': 0.2
        }
        self.debug = ['move_answers']

    def get_effect(self, scoreboard):
        """
        determines the items for every player
        """
        sorted_scoreboard = sorted(scoreboard.items(), key=lambda kv: kv[1], reverse=True)
        effect_distribution = {}

        for player in sorted_scoreboard:
            # position relative = (position in scoreboard / number of players)
            position_relative = (sorted_scoreboard.index(player)) / (len(sorted_scoreboard))
            lower_bound = position_relative - CONSTANTS.RELATIVE_POSITION_DEVIATION
            if lower_bound < 0:
                lower_bound = 0
            upper_bound = position_relative + CONSTANTS.RELATIVE_POSITION_DEVIATION
            considered_items = {}
            for item in self.possible_effects:
                if self.possible_effects[item] >= lower_bound and self.possible_effects[item] <= upper_bound:
                    considered_items[item] = item
            if considered_items:
                effect_distribution[player[0]] = random.choice(list(considered_items))  #player[0] because it is a tuple, we only need id though
        return effect_distribution


class ItemTable:
    def __init__(self):
        self.player_items = {}  # {item:{p_id1:quantity1,p_id2:quantity2,...},...}

    def get_player_items(self):
        return self.player_items

    def add_item(self, item, p_id):
        if item not in self.player_items:
            self.player_items[item] = {}
            self.player_items[item][p_id] = 1
        else:
            if p_id not in self.player_items[item]:
                self.player_items[item][p_id] = 1
            else:
                self.player_items[item][p_id] += 1

    def check_and_activate_item(self, item, p_id):
        if item not in self.player_items:
            return False
        else:
            if p_id not in self.player_items[item]:
                return False
            else:
                if self.player_items[item][p_id] > 0:
                    self.player_items[item][p_id] -= 1
                    return True

    def clean(self):
        for element in self.player_items:
            for k, v in self.player_items[element].items():
                if v <= 0:
                    del self.player_items[element][k]
            if not element:
                del self.player_items[element]


class Protocol:
    """
    logging utility to handle socket interrupts
    defines set of states for each player:
    - joined_lobby      : lobby id
    - joined_game       : game id
    - got_question      : latest received question id
    - answered_question : latest answered question
    - got_scoreboard    : true/false
    """
    def __init__(self, lobby_id):
        self.lobby_id = lobby_id
        self.game_id = -1
        self.states = ['joined_lobby', 'joined_game', 'got_question', 'answered_question', 'got_scoreboard']
        self.table = {}  # {player_id: {states}}
        self._default_table = {key: None for key in self.states}  # default states when a player is added

    def add_player(self, player_id):
        if player_id not in self.table:  # only add the player if it isnt already present (prevent overwriting of their log)
            self.table[player_id] = self._default_table

    def put(self, player_id, state, state_value):
        """
        add a new state to the protocol
        :param player_id: the player id
        :param state: the state to add a value to. must be a valid one
        :param state_value: the value to assign to the state
        """
        if state in self.states:  # only if state is valid, i.e. it is defined
            if player_id in self.table:  # only if player was added before
                self.table[player_id][state] = state_value
            else:
                warnings.warn('Player was not added to the protocol before. Function will have no effect.', Warning)
        else:
            warnings.warn('State is not valid. Function will have no effect. (maybe typo?)', Warning)
