import time
import sys
import threading
import struct
import json
from multiprocessing.connection import Listener
import os

class GameMonitorCommunication:
    def __init__(self):
        address = ('localhost', 6000)     # family is deduced to be 'AF_INET'
        self.listener = Listener(address, authkey=b'xtoysnotverysecretkey')
        self.conn = self.listener.accept()
    
    # Send message to other process
    def send_message(self, message):
        self.conn.send(message)
    
    # Listen for messages from other process and immediately pass through to Chrome extension
    def monitor_loop(self, chrome_ext):
        while True:
            message = self.conn.recv()
            chrome_ext.send_message(message)

class ChromeExtensionCommunication:
    def encode_message(self, messageContent):
        encodedContent = json.dumps(messageContent).encode('utf-8')
        encodedLength = struct.pack('@I', len(encodedContent))
        return {'length': encodedLength, 'content': encodedContent}
    
    # Send message to Chrome extension
    def send_message(self, message):
        encoded_message = self.encode_message(message)
        sys.stdout.buffer.write(encoded_message['length'])
        sys.stdout.buffer.write(encoded_message['content'])
        sys.stdout.buffer.flush()

    # Listen for messages from Chrome extension and immediately pass through to other process
    def monitor_loop(self, game_monitor):
        while True:
            raw_length = sys.stdin.buffer.read(4)
            if not raw_length:
                sys.exit(0)
            message_length = struct.unpack('i', raw_length)[0]
            message = sys.stdin.buffer.read(message_length).decode('utf-8')
            game_monitor.send_message(message)

def main():
    version = "1.0"

    # Launch other process (exe if Game Monitor has been compiled, python file otherwise)
    if getattr(sys, 'frozen', False):
        os.system('START /b game-monitor.exe')
    elif __file__:
        os.system('START /b python game-monitor.py')
    
    game_monitor = GameMonitorCommunication()
    chrome_ext = ChromeExtensionCommunication()
    
    chrome_ext.send_message({ "version": version })
    
    thread = threading.Thread(target=game_monitor.monitor_loop, args=(chrome_ext,))
    thread.daemon = True
    thread.start()
    
    chrome_ext.monitor_loop(game_monitor,)

if __name__ == '__main__':
    main()
