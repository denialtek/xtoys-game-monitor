import time
import threading
import pymem
import json
from multiprocessing.connection import Client
from elevate import elevate
import logging
import traceback

# This file must be run as admin so that it has permission to read process memory
elevate(show_console=False)

formatter = logging.Formatter(fmt='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
handler = logging.FileHandler('xtoys.log', mode = 'w')
handler.setFormatter(formatter)
logger = logging.getLogger('xtoys')
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

class GameMonitor:
    def __init__(self):
        self.pm = None
        self.modules = {}
        self.variables = {}
    
    def monitor_game(self, state, comm):
        logger = logging.getLogger('xtoys')
        try:
            while True:
                if self.pm is None:
                    # No data defined
                    if 'name' not in state:
                        time.sleep(1)
                        continue
                    # Try to find game
                    try:
                        self.pm = pymem.Pymem(state['name'])
                    except Exception as e:
                        time.sleep(1)
                        continue

                    logger.debug(state['name'] + ' game found')
                    
                    # Find all base addresses
                    modules_list = list(self.pm.list_modules())
                    for module in modules_list:
                        self.modules[module.name] = module
                    
                    state["game_active"] = True
                    comm.send_message({ "event": "active_changed", "state": True })

                # Loop through state values
                for name, scan_entry in state['scan_data'].items():
                    changed = False

                    if 'address' not in scan_entry:
                        # Find final address
                        address = 0
                        stop_address = 0x7fffffffffff
                        if 'start_from_type' in scan_entry and 'start_from' in scan_entry:
                            start_from = scan_entry['start_from']
                            start_from_type = scan_entry['start_from_type']
                            if start_from_type == 'module':
                                if start_from not in self.modules:
                                    scan_entry['address'] = -1
                                    scan_entry['result'] = -1
                                    logger.debug(scan_entry['name'] + ': ' + start_from + ' module not found')
                                    continue # Skipping if invalid module name was given for this scan_entry
                                module = self.modules[start_from]
                                address = module.lpBaseOfDll
                                stop_address = address + module.SizeOfImage
                            elif start_from_type == 'variable':
                                if start_from not in self.variables:
                                    scan_entry['address'] = -1
                                    scan_entry['result'] = -1
                                    logger.debug(scan_entry['name'] + ': ' + start_from + ' variable not found')
                                    continue # Skipping if invalid variable name was given for this scan_entry
                                address = self.variables[start_from]
                            elif start_from_type == 'static':
                                address = start_from
                        
                        if 'aob' in scan_entry:
                            bytesArr = bytes.fromhex(scan_entry['aob'].replace('.', '2E'))
                            page_address = address
                            while page_address < stop_address:
                                next_page, found_address = pymem.pattern.scan_pattern_page(self.pm.process_handle, page_address, bytesArr)
                                if found_address:
                                    address = found_address
                                    break
                                page_address = next_page
                        
                        if 'offset' in scan_entry:
                            address += scan_entry['offset']

                        if 'pointers' in scan_entry:
                            pointers = scan_entry['pointers']
                            address = self.pm.read_int(address)
                            for pointer in pointers[:-1]:
                                address = self.pm.read_int(address + pointer)
                            address = address + pointers[-1]

                        self.variables[name] = address
                        scan_entry['address'] = address
                        logger.debug(name + ': Address ' + hex(address))

                    address = scan_entry['address']
                    if address == -1: # Skip scan_entries where we failed to find a valid address
                        continue
                    # read in the value we're looking for
                    val_type = scan_entry['type']
                    result = None
                    if val_type == 'char':
                        result = self.pm.read_char(address)
                    elif val_type == 'short':
                        result = self.pm.read_short(address)
                    elif val_type == 'int':
                        result = self.pm.read_int(address)
                    elif val_type == 'long':
                        result = self.pm.read_long(address)
                    elif val_type == 'longlong':
                        result = self.pm.read_longlong(address)
                    elif val_type == 'double':
                        result = self.pm.read_double(address)
                    elif val_type == 'float':
                        result = self.pm.read_float(address)
                    elif val_type == 'string':
                        result = self.pm.read_string(address, scan_entry['length'])
                    elif val_type == 'bytes':
                        result = int.from_bytes(self.pm.read_bytes(address, scan_entry['length']), 'big')
                    if 'result' not in scan_entry or result != scan_entry['result']:
                        scan_entry['result'] = result
                        logger.debug(name + ': Value ' + str(result))
                        changed = True

                    # If something changed notify the other process so it can send the data to the XToys Chrome extension
                    if changed:
                        comm.send_message({"event": "entry_changed", "name": name, "scan_data": scan_entry })
                time.sleep(0.1)
        
        except Exception:
            logger.debug(traceback.format_exc())

class Communication:
    def __init__(self):
        address = ('localhost', 6000)
        while True:
            try:
                self.conn = Client(address, authkey=b'xtoysnotverysecretkey')
                return
            except Exception as e:
                time.sleep(1)
        
    # Send message to other process
    def send_message(self, message):
        self.conn.send(message)

    # Listen for messages from other process
    def monitor_loop(self, state, game_monitor):
        
        logger = logging.getLogger('xtoys')

        while True:
            message = self.conn.recv()
            logger.debug('Message from XToys: ' + message)
            json_data = json.loads(message)
            action = json_data['action']
            if action == 'set_name':
                # If XToys asked to change games, clear existing process monitor
                if 'name' in state and state['name'] != json_data['name']:
                    game_monitor.pm = None
                    state['game_active'] = False
                state['name'] = json_data['name']
            elif action == 'set_scan_entry':
                name = json_data['name']
                state['scan_data'][name] = json_data['scan_data']

def main():
    state = {
        "scan_data": {}
    }
    
    communication = Communication()
    game_monitor = GameMonitor()
    
    thread = threading.Thread(target=game_monitor.monitor_game, args=(state,communication))
    thread.daemon = True
    thread.start()
    
    communication.monitor_loop(state, game_monitor)

if __name__ == '__main__':
    main()
