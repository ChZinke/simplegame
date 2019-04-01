import json
import time
from multiprocessing import Process
import tornado.ioloop
import tornado.web
import tornado.websocket
from logic import *
from model import *


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('index.html')


class SimpleWebSocket(tornado.websocket.WebSocketHandler):
    connections = set()
    pid = ''

    def open(self, username):
        self.connections.add(self)

    def on_message(self, message):
        msg = json.loads(message)
        print("incoming message: " + message)
        if 'type' in msg:  # 'type' always needs to be in an incoming message
            if msg['type'] == 'login':
                username = msg['user']
                player_id = get_player_id(username)
                self.pid = player_id if player_id is not None else -1  # -1 indicates login error
                auth_msg = json.dumps({'type': 'login',
                                       'p_id': self.pid})
                self.write_message(auth_msg)  # authentification message only to this one client
            elif msg['type'] == 'user_message':
                self.notify_clients(json.dumps(msg))
            elif msg['type'] == 'join_lobby':
                player_id = msg['p_id']
                player = get_player(player_id)
                # TODO when quiz model implemented: quiz_id needs to be supplied
                LobbyPool.join_lobby(player, self)  # TODO when quiz model implemented: quiz_id as 3rd parameter
            elif msg['type'] == 'leave_lobby':
                player_id = msg['p_id']
                player = get_player(player_id)
                LobbyPool.leave_lobby(player)
            elif msg['type'] == 'answered_question':
                if all(key in msg for key in ('game_id', 'q_id')):  # we now also need game_id and q_id for played_questions
                    player_id = msg['p_id']
                    game_id = msg['game_id']
                    question_id = msg['q_id']
                    GamePool.get_game(game_id).add_waiting_player(player_id)
                    # TODO when PlayedQuestion Model exists: check if keys for pq exists, generate pq, add pq tp game
            else:
                print('Could not resolve "type" key: ' + msg['type'])

        else:
            print('Message Error, keys "type"  and/or "p_id" not supplied in incoming message')

    def notify_clients(self, message):
        for client in self.connections:
            client.write_message(message)

    def on_close(self):
        self.connections.remove(self)
        print('connection closed')


def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/websocket", SimpleWebSocket),
        (r"/websocket/username/(.*)", SimpleWebSocket)
    ])


if __name__ == '__main__':
    app = make_app()
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()