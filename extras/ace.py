import serial, threading, time, logging, json, struct, queue, traceback, re
from serial import SerialException
import serial.tools.list_ports


class AceException(Exception):
    pass

ACTION_IDLE = 'Idle'
ACTION_LOADING = 'Loading'
ACTION_LOADING_EXTRUDER = 'Loading Ext'
ACTION_UNLOADING = 'Unloading'
ACTION_UNLOADING_EXTRUDER = 'Unloading Ext'
ACTION_FORMING_TIP = 'Forming Tip'
ACTION_CUTTING_TIP = 'Cutting Tip'
ACTION_HEATING = 'Heating'
ACTION_CHECKING = 'Checking'
ACTION_HOMING = 'Homing'
ACTION_SELECTING = 'Selecting'
ACTION_CUTTING_FILAMENT = 'Cutting Filament'
ACTION_PURGING = 'Purging'

FILAMENT_POS_UNKNOWN = -1
FILAMENT_POS_UNLOADED = 0 # Parked in gate
FILAMENT_POS_HOMED_GATE = 1 # Homed at either gate or gear sensor (currently assumed mutually exclusive sensors)
FILAMENT_POS_START_BOWDEN = 2 # Point of fast load portion
FILAMENT_POS_IN_BOWDEN = 3 # Some unknown position in the bowden
FILAMENT_POS_END_BOWDEN = 4 # End of fast load portion
FILAMENT_POS_HOMED_ENTRY = 5 # Homed at entry sensor
FILAMENT_POS_HOMED_EXTRUDER = 6 # Collision homing case at extruder gear entry
FILAMENT_POS_EXTRUDER_ENTRY = 7 # Past extruder gear entry
FILAMENT_POS_HOMED_TS = 8 # Homed at toolhead sensor
FILAMENT_POS_IN_EXTRUDER = 9 # In extruder past toolhead sensor
FILAMENT_POS_LOADED = 10 # Homed to nozzle

GATE_UNKNOWN = -1
GATE_EMPTY = 0
GATE_AVAILABLE = 1 # Available to load from either buffer or spool


class BunnyAce:
    VARS_ACE_REVISION = 'ace__revision'

    def __init__(self, config):
        self._connected = False
        self._serial = None
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self._name = config.get_name()
        self.send_time = None
        self.ace_dev_fd = None
        self.heatbeat_timer = None

        self.gate_color = ['ffffff', 'ffffff', 'ffffff', 'ffffff']
        self.gate_material = ['PLA', 'PLA', 'PLA', 'PLA']
        self.gate_name = ['PLA', 'PLA', 'PLA', 'PLA']
        self.gate_temp = [220, 220, 220, 220]
        self.gate_speed = [100, 100, 100, 100]
        self.gate_spool_id = [-1, -1, -1, -1]
        self.gate_status = [GATE_UNKNOWN, GATE_UNKNOWN, GATE_UNKNOWN, GATE_UNKNOWN]
        self.ttg_map = [0, 1, 2, 3]
        self.last_tool = -1
        self.next_tool = -1
        self.current_gate = -1
        self.num_toolchanges = 0
        self.error_msg = ""
        self.ace_action = ACTION_IDLE
        self.filament_pos = FILAMENT_POS_UNLOADED

        self.read_buffer = bytearray()
        if self._name.startswith('ace '):
            self._name = self._name[4:]

        self.save_variables = self.printer.lookup_object('save_variables', None)
        if self.save_variables:
            revision_var = self.save_variables.allVariables.get(self.VARS_ACE_REVISION, None)
            if revision_var is None:
                config.error("You have custom [save_variables]. "
                             "Copy the contents of ace_vars.cfg to your file and remove [save_variables] in ace.cfg")
        else:
            config.error("There is no [save_variables] in the config. Check installation guide")

        for var, attr in [('ace_gate_color', 'gate_color'),
                          ('ace_gate_type', 'gate_material'),
                          ('ace_gate_name', 'gate_name'),
                          ('ace_gate_speed', 'gate_speed'),
                          ('ace_gate_spool_id', 'gate_spool_id'),
                          ('ace_gate_temp', 'gate_temp')]:
            value = self.save_variables.allVariables.get(var, getattr(self, attr))
            setattr(self, attr, value)

        self.current_gate = self.save_variables.allVariables.get('ace_current_index', -1)
        self.filament_pos = self.save_variables.allVariables.get('ace_filament_pos', FILAMENT_POS_UNKNOWN)


        self.serial_id = config.get('serial', '/dev/ttyACM0')
        self.baud = config.getint('baud', 115200)

        self.extruder_sensor_name = config.get('extruder_sensor_name')
        self.toolhead_sensor_name = config.get('toolhead_sensor_name', None)
        self.feed_speed = config.getint('feed_speed', 50)
        self.retract_speed = config.getint('retract_speed', 50)
        self.toolchange_retract_length = config.getint('toolchange_retract_length', 100)
        self.toolchange_feed_length = config.getint('toolchange_feed_length', 100)
        self.toolhead_homing_max = config.getint('toolhead_homing_max', 100)
        self.toolhead_homing_speed = config.getint('toolhead_homing_speed', 10)
        self.extruder_move_speed = config.getint('extruder_move_speed', 10)
        self.toolhead_sensor_to_nozzle_length = config.getint('toolhead_sensor_to_nozzle', 0)
        self.poop_macros = config.get('poop_macros')
        self.cut_macros = config.get('cut_macros')

        # self.extruder_to_blade_length = config.getint('extruder_to_blade', None)

        self.max_dryer_temperature = config.getint('max_dryer_temperature', 55)

        self._callback_map = {}
        self._feed_assist_index = -1
        self._request_id = 0

        # Default data to prevent exceptions
        self._info = {
            'status': 'ready',
            'dryer_status': {
                'status': 'stop',
                'target_temp': 0,
                'duration': 0,
                'remain_time': 0
            },
            'temp': 0,
            'enable_rfid': 1,
            'fan_speed': 7000,
            'feed_assist_count': 0,
            'cont_assist_time': 0.0,
            'slots': [
                {
                    'index': 0,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                },
                {
                    'index': 1,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                },
                {
                    'index': 2,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                },
                {
                    'index': 3,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                }
            ]
        }
        self.extruder_sensor = None

        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        self.printer.register_event_handler('klippy:disconnect', self._handle_disconnect)

        self.gcode.register_command(
            'ACE_DEBUG', self.cmd_ACE_DEBUG,
            desc='self.cmd_ACE_DEBUG_help')
        self.gcode.register_command(
            'ACE_START_DRYING', self.cmd_ACE_START_DRYING,
            desc=self.cmd_ACE_START_DRYING_help)
        self.gcode.register_command(
            'ACE_STOP_DRYING', self.cmd_ACE_STOP_DRYING,
            desc=self.cmd_ACE_STOP_DRYING_help)
        self.gcode.register_command(
            'ACE_ENABLE_FEED_ASSIST', self.cmd_ACE_ENABLE_FEED_ASSIST,
            desc=self.cmd_ACE_ENABLE_FEED_ASSIST_help)
        self.gcode.register_command(
            'ACE_DISABLE_FEED_ASSIST', self.cmd_ACE_DISABLE_FEED_ASSIST,
            desc=self.cmd_ACE_DISABLE_FEED_ASSIST_help)
        self.gcode.register_command(
            'ACE_FEED', self.cmd_ACE_FEED,
            desc=self.cmd_ACE_FEED_help)
        self.gcode.register_command(
            'ACE_RETRACT', self.cmd_ACE_RETRACT,
            desc=self.cmd_ACE_RETRACT_help)
        self.gcode.register_command(
            'ACE_CHANGE_TOOL', self.cmd_ACE_CHANGE_TOOL,
            desc=self.cmd_ACE_CHANGE_TOOL_help)
        self.gcode.register_command(
            'ACE_GATE_MAP', self.cmd_ACE_GATE_MAP,
            desc=self.cmd_ACE_GATE_MAP_help)
        self.gcode.register_command(
            'ACE_ENDLESS_SPOOL', self.cmd_ACE_ENDLESS_SPOOL,
            desc=self.cmd_ACE_ENDLESS_SPOOL_help
        )
        self.gcode.register_command(
            'ACE_SENSOR_RUNOUT', self.extruder_sensor_handler,
            desc=self.cmd_ACE_SENSOR_RUNOUT_help
        )

    def _handle_ready(self):
        self.toolhead = self.printer.lookup_object('toolhead')

        self.pause_resume = self.printer.lookup_object('pause_resume', None)
        if self.pause_resume is None:
            raise self.printer.config_error("ACE requires [pause_resume] to work, please add it to your config!")

        self.extruder_sensor = self.printer.lookup_object(f'filament_switch_sensor %s' % self.extruder_sensor_name)
        if self.extruder_sensor is None:
            self.printer.config_error("[filament_switch_sensor %s] not found" % self.extruder_sensor_name)

        logging.info('ACE: Connecting to ' + self.serial_id)
        # We can catch timing where ACE reboots itself when no data is available from host. We're avoiding it with this hack
        self._connected = False
        self._queue = queue.Queue()
        self.connect_timer = self.reactor.register_timer(self._connect, self.reactor.NOW)

    def _handle_disconnect(self):
        logging.info('ACE: Closing connection to ' + self.serial_id)
        self._serial_disconnect()
        self._queue = None

    def _color_message(self, msg):
        try:
            html_msg = msg.format(
                '</span>',  # {0}
                '<span style="color:#FFFF00">',  # {1}
                '<span style="color:#90EE90">',  # {2}
                '<span style="color:#458EFF">',  # {3}
                '<b>',  # {5}
                '</b>'  # {6}
            )
        except (IndexError, KeyError, ValueError) as e:
            html_msg = msg
        return html_msg

    def log_warning(self, msg):
        c_msg = self._color_message('{1}%s{0}' % msg)
        self.gcode.respond_raw(c_msg)

    def log_always(self, msg, color=False):
        c_msg = self._color_message(msg) if color else msg
        self.gcode.respond_raw(c_msg)

    def log_error(self, msg):
        self.error_msg = msg
        self.gcode.respond_raw("!! %s" % msg)

    def save_variable(self, variable, value, write=False):
        self.save_variables.allVariables[variable] = value
        if write:
            self.write_variables()

    def delete_variable(self, variable, write=False):
        _ = self.save_variables.allVariables.pop(variable, None)
        if write:
            self.write_variables()

    def write_variables(self):
        mmu_vars_revision = self.save_variables.allVariables.get(self.VARS_ACE_REVISION, 0) + 1
        self.gcode.run_script_from_command(
            "SAVE_VARIABLE VARIABLE=%s VALUE=%d" % (self.VARS_ACE_REVISION, mmu_vars_revision))


    def _get_next_request_id(self) -> int:
        self._request_id += 1
        if self._request_id >= 300000:
            self._request_id = 0
        return self._request_id

    def _serial_disconnect(self):

        if self._serial is not None and self._serial.is_open:
            self._serial.close()
            self._connected = False
        if self.heatbeat_timer:
            self.reactor.unregister_timer(self.heatbeat_timer)
        if self.ace_dev_fd:
            self.reactor.set_fd_wake(self.ace_dev_fd, False, False)
            self.ace_dev_fd = None

    def _connect(self, eventtime):
        self.log_always('Try connecting')

        def info_callback(self, response):
            if 'msg' in response and response['msg'] != 'success':
                self.log_error("ACE Error: " + response['msg'])
            self.log_always("{2}ACE: Connected to %s {0} \n Firmware Version: {3}%s{0}" %
                            (response['result']['model'], response['result']['firmware']), True)

        try:
            self._serial = serial.Serial(
                port=self.serial_id,
                baudrate=self.baud,
                exclusive=True,
                rtscts=True,
                timeout=0,
                write_timeout=0)

            if self._serial.is_open:
                self._connected = True
                self._request_id = 0
                logging.info('ACE: Connected to ' + self.serial_id)
                self.ace_dev_fd = self.reactor.register_fd(
                    self._serial.fileno(),
                    self._reader,
                    self._writer
                )
                self.heatbeat_timer = self.reactor.register_timer(self._periodic_heartbeat_event, self.reactor.NOW)
                self.send_request(request={"method": "get_info"},
                                  callback=lambda self, response: info_callback(self, response))
                if self._feed_assist_index != -1:
                    self._enable_feed_assist(self._feed_assist_index)
                self.reactor.unregister_timer(self.connect_timer)
                return self.reactor.NEVER
        except serial.serialutil.SerialException:
            self._serial = None
            logging.info('ACE: Conn error')
            self.log_error('Error connecting to ' + self.serial_id)
        except Exception as e:
            self.log_error("ACE Error: %s" % str(e))

        return eventtime + 1

    def _calc_crc(self, buffer):
        _crc = 0xffff
        for byte in buffer:
            data = byte
            data ^= _crc & 0xff
            data ^= (data & 0x0f) << 4
            _crc = ((data << 8) | (_crc >> 8)) ^ (data >> 4) ^ (data << 3)
        return _crc

    def _send_request(self, request):
        if not 'id' in request:
            request['id'] = self._get_next_request_id()

        payload = json.dumps(request)
        payload = bytes(payload, 'utf-8')

        data = bytes([0xFF, 0xAA])
        data += struct.pack('@H', len(payload))
        data += payload
        data += struct.pack('@H', self._calc_crc(payload))
        data += bytes([0xFE])
        self._serial.write(data)

    def _periodic_heartbeat_event(self, eventtime):
        def callback(self, response):
            if response is not None:
                self._info = response['result']
                self.gate_status = [GATE_EMPTY if data['status'] == 'empty' else GATE_AVAILABLE
                                    for data in self._info['slots']]

        self.send_request({"method": "get_status"}, callback)
        return eventtime + 2.5

    def _reader(self, eventtime):
        try:
            if self._serial.in_waiting:
                raw_bytes = self._serial.read(size=self._serial.in_waiting)
            else:
                raw_bytes = bytearray()
        except Exception as e:
            self.log_error("Unable to communicate with the ACE PRO")
            self.log_warning("Try reconnecting")
            logging.info('ACE error: ' + traceback.format_exc())
            self._serial_disconnect()
            self.connect_timer = self.reactor.register_timer(self._connect, self.reactor.NOW)
            return

        if len(raw_bytes):
            text_buffer = self.read_buffer + raw_bytes
            i = text_buffer.find(b'\xfe')
            if i >= 0:
                buffer = text_buffer
                self.read_buffer = bytearray()
            else:
                self.read_buffer += raw_bytes
                return
        else:
            return

        if len(buffer) < 7:
            return

        if buffer[0:2] != bytes([0xFF, 0xAA]):
            self.gcode.respond_info("Invalid data from ACE PRO (head bytes)")
            self.gcode.respond_info(str(buffer))
            return

        payload_len = struct.unpack('<H', buffer[2:4])[0]
        # logging.info(str(buffer))
        payload = buffer[4:4 + payload_len]

        crc_data = buffer[4 + payload_len:4 + payload_len + 2]
        crc = struct.pack('@H', self._calc_crc(payload))

        if len(buffer) < (4 + payload_len + 2 + 1):
            self.gcode.respond_info(f"Invalid data from ACE PRO (len) {payload_len} {len(buffer)} {crc}")
            self.gcode.respond_info(str(buffer))
            return

        if crc_data != crc:
            self.gcode.respond_info('Invalid data from ACE PRO (CRC)')

        ret = json.loads(payload.decode('utf-8'))
        id = ret['id']
        if id in self._callback_map:
            callback = self._callback_map.pop(id)
            callback(self=self, response=ret)

    def _writer(self, eventtime):
        try:
            if not self._queue.empty():
                task = self._queue.get()
                if task is not None:
                    id = self._get_next_request_id()
                    self._callback_map[id] = task[1]
                    task[0]['id'] = id
                    self._send_request(task[0])
                    self.send_time = eventtime
        except Exception:
            logging.info('ACE error: ' + traceback.format_exc())
            self.gcode.respond_info('Try reconnecting')
            self._serial_disconnect()
            self.connect_timer = self.reactor.register_timer(self._connect, self.reactor.NOW)

    def send_request(self, request, callback):
        self._info['status'] = 'busy'
        if self.ace_dev_fd:
            self.reactor.set_fd_wake(self.ace_dev_fd, True, True)
        self._queue.put([request, callback])


    def wait_ace_ready(self):
        while self._info['status'] != 'ready':
            currTs = self.reactor.monotonic()
            self.reactor.pause(currTs + .5)

    def is_ace_ready(self):
        return self._info['status'] == 'ready'

    def dwell(self, delay=1.):
        currTs = self.reactor.monotonic()
        self.reactor.pause(currTs + delay)

    def _extruder_move(self, length, speed):
        pos = self.toolhead.get_position()
        pos[3] += length
        self.toolhead.move(pos, speed)
        return pos[3]

    cmd_ACE_SENSOR_RUNOUT_help = 'Extruder sensor runout gcode'

    def extruder_sensor_handler(self, gcmd):
        was_index = self.current_gate
        now = self.reactor.monotonic()
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            is_printing = print_stats.get_status(now)["state"] == "printing"
        else:
            is_printing = self.printer.lookup_object("idle_timeout").get_status(now)["state"] == "Printing"

        if (not self.extruder_sensor.runout_helper.filament_present) and self._info['slots'][was_index]['status'] == 'empty' and is_printing:
            ace_material = self.gate_material
            self.current_gate = -1
            self.save_variable('ace_current_index', -1, True)
            self.pause_resume.send_pause_command()

            if self.save_variables.allVariables.get('ace_endless_spool', False):
                self.log_always('Endless spool')
                spools = list(filter(lambda x: x['status'] != 'empty'
                                               and ace_material[x['index']] == ace_material[was_index],
                                     self._info['slots']))
                if len(spools) == 0:
                    self.log_warning("There are no suitable spools for an endless spool. Print pause")
                    return
                self.log_always('{2}Change to spool: %s{0}' % spools[0]["index"], True)
                self.gcode.run_script_from_command(f'T{spools[0]["index"]}')
                self.pause_resume.send_resume_command()
            else:
                self.log_warning('Filament runout! Endless spool disabled')


    cmd_ACE_START_DRYING_help = 'Starts ACE Pro dryer'

    def cmd_ACE_START_DRYING(self, gcmd):
        temperature = gcmd.get_int('TEMP')
        duration = gcmd.get_int('DURATION', 240)

        if duration <= 0:
            raise gcmd.error('Wrong duration')
        if temperature <= 0 or temperature > self.max_dryer_temperature:
            raise gcmd.error('Wrong temperature')

        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
                return

            self.gcode.respond_info('Started ACE drying')

        self.wait_ace_ready()
        self.send_request(
            request={"method": "drying", "params": {"temp": temperature, "fan_speed": 7000, "duration": duration}},
            callback=callback)

    cmd_ACE_STOP_DRYING_help = 'Stops ACE Pro dryer'

    def cmd_ACE_STOP_DRYING(self, gcmd):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
                return

            self.gcode.respond_info('Stopped ACE drying')

        self.wait_ace_ready()
        self.send_request(request={"method": "drying_stop"}, callback=callback)

    def _enable_feed_assist(self, index):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
            else:
                self._feed_assist_index = index



        self.wait_ace_ready()
        self.send_request(request={"method": "start_feed_assist", "params": {"index": index}}, callback=callback)
        self.dwell(delay=0.7)

    cmd_ACE_ENABLE_FEED_ASSIST_help = 'Enables ACE feed assist'

    def cmd_ACE_ENABLE_FEED_ASSIST(self, gcmd):
        index = gcmd.get_int('INDEX')

        if index < 0 or index >= 4:
            raise gcmd.error('Wrong index')

        self._enable_feed_assist(index)

    def _disable_feed_assist(self, index=-1):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
                return

            self._feed_assist_index = -1
            self.gcode.respond_info('Disabled ACE feed assist')

        self.wait_ace_ready()
        self.send_request(request={"method": "stop_feed_assist", "params": {"index": self._feed_assist_index}}, callback=callback)
        self.dwell(0.3)

    cmd_ACE_DISABLE_FEED_ASSIST_help = 'Disables ACE feed assist'

    def cmd_ACE_DISABLE_FEED_ASSIST(self, gcmd):
        if self._feed_assist_index != -1:
            index = gcmd.get_int('INDEX', self._feed_assist_index)
        else:
            index = gcmd.get_int('INDEX')

        if index < 0 or index >= 4:
            raise gcmd.error('Wrong index')

        self._disable_feed_assist(index)

    def _feed(self, index, length, speed, how_wait=None):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
                return

        self.wait_ace_ready()
        self.send_request(
            request={"method": "feed_filament", "params": {"index": index, "length": length, "speed": speed}},
            callback=callback)
        if how_wait is not None:
            self.dwell(delay=(how_wait / speed) + 0.1)
        else:
            self.dwell(delay=(length / speed) + 0.1)

    cmd_ACE_FEED_help = 'Feeds filament from ACE'

    def cmd_ACE_FEED(self, gcmd):
        index = gcmd.get_int('INDEX')
        length = gcmd.get_int('LENGTH')
        speed = gcmd.get_int('SPEED', self.feed_speed)

        if index < 0 or index >= 4:
            raise gcmd.error('Wrong index')
        if length <= 0:
            raise gcmd.error('Wrong length')
        if speed <= 0:
            raise gcmd.error('Wrong speed')

        self._feed(index, length, speed)

    def _retract(self, index, length, speed):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
                return

        self.wait_ace_ready()
        self.send_request(
            request={"method": "unwind_filament", "params": {"index": index, "length": length, "speed": speed}},
            callback=callback)
        self.dwell(delay=(length / speed) + 0.1)

    cmd_ACE_RETRACT_help = 'Retracts filament back to ACE'

    def cmd_ACE_RETRACT(self, gcmd):
        index = gcmd.get_int('INDEX')
        length = gcmd.get_int('LENGTH')
        speed = gcmd.get_int('SPEED', self.retract_speed)

        if index < 0 or index >= 4:
            raise gcmd.error('Wrong index')
        if length <= 0:
            raise gcmd.error('Wrong length')
        if speed <= 0:
            raise gcmd.error('Wrong speed')

        self._retract(index, length, speed)

    def _set_feeding_speed(self, index, speed):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])

        self.send_request(
            request={"method": "update_feeding_speed", "params": {"index": index, "speed": speed}},
            callback=callback)

    def _stop_feeding(self, index):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                self.log_error("ACE Error: " + response['msg'])
                return

        self.send_request(
            request={"method": "stop_feed_filament", "params": {"index": index}},
            callback=callback)

    def _park_to_toolhead(self, tool):
        self.current_gate = tool

        self.wait_ace_ready()
        self.ace_action = ACTION_LOADING
        self.filament_pos = FILAMENT_POS_START_BOWDEN

        start_fast_feed = self.reactor.monotonic()
        self._feed(tool,
                   self.toolchange_feed_length + self.toolhead_homing_max,
                   self.feed_speed,
                   0
                   )

        self.filament_pos = FILAMENT_POS_IN_BOWDEN
        self.save_variable('ace_filament_pos', self.filament_pos, True)

        while not bool(self.extruder_sensor.runout_helper.filament_present):
            if (start_fast_feed and
                    (self.reactor.monotonic() - start_fast_feed) >= (self.toolchange_feed_length//self.feed_speed)):
                self._set_feeding_speed(tool, self.toolhead_homing_speed)
                start_fast_feed = 0
                self.filament_pos = FILAMENT_POS_END_BOWDEN
                self.save_variable('ace_filament_pos', self.filament_pos, True)

            if self.is_ace_ready():
                raise AceException('ACE Error: Load failed: Failed to reach extruder sensor')
            self.dwell(delay=0.01)


        self._stop_feeding(tool)
        self.filament_pos = FILAMENT_POS_HOMED_EXTRUDER
        self.save_variable('ace_filament_pos', self.filament_pos, True)

        self.wait_ace_ready()

        self._enable_feed_assist(tool)

        self.ace_action = ACTION_LOADING_EXTRUDER
        self.filament_pos = FILAMENT_POS_HOMED_EXTRUDER
        if self.toolhead_sensor_name:
            toolhead_sensor = self.printer.lookup_object("filament_switch_sensor %s" % self.toolhead_sensor_name, None)
            while not bool(toolhead_sensor.runout_helper.filament_present):
                self._extruder_move(1, self.extruder_move_speed)
                self.dwell(delay=0.01)

        self.save_variable('ace_filament_pos', self.filament_pos, True)

        self._extruder_move(self.toolhead_sensor_to_nozzle_length, self.extruder_move_speed)
        self.filament_pos = FILAMENT_POS_EXTRUDER_ENTRY

        gcode_move = self.printer.lookup_object('gcode_move')
        gcode_move.reset_last_position()
        self.ace_action = ACTION_PURGING

        self.filament_pos = FILAMENT_POS_LOADED
        self.save_variable('ace_filament_pos', self.filament_pos, True)
        self.gcode.run_script_from_command(self.poop_macros)
        self.ace_action = ACTION_IDLE

    def cmd_ACE_TTG_MAP(self, gcmd):
        tool = gcmd.get_int('TOOL')
        gate = gcmd.get_int('GATE')
        self.ttg_map[gate] = tool
        self.save_variable('ace_ttg_map', self.ttg_map, True)

    cmd_ACE_CHANGE_TOOL_help = 'Changes tool'
    def cmd_ACE_CHANGE_TOOL(self, gcmd):
        tool = gcmd.get_int('TOOL', None)
        gate = gcmd.get_int('GATE', None)

        if tool is not None:
            gate = self.ttg_map[tool]
        elif gate is not None:
            if gate < -1 or gate >= 4:
                raise gcmd.error('Wrong tool')
        else:
            raise gcmd.error('Missing parameter TOOL or GATE')

        if self.current_gate == gate:
            self.log_warning('ACE: Not changing tool, current index already ' + str(gate))
            return

        if gate != -1:
            status = self._info['slots'][gate]['status']
            if status != 'ready':
                self.log_error("ACE Error: This spool is not ready")
                self.gcode.run_script_from_command('_ACE_ON_EMPTY_ERROR INDEX=' + str(gate))
                return

        self.last_tool = self.current_gate
        self.next_tool = gate


        self.ace_action = ACTION_HEATING
        self.gcode.run_script_from_command('_ACE_PRE_TOOLCHANGE FROM=' + str(self.last_tool) + ' TO=' + str(gate))

        logging.info('ACE: Toolchange ' + str(self.last_tool) + ' => ' + str(gate))
        self.log_always('ACE: Toolchange ' + str(self.last_tool) + ' => ' + str(gate))

        if self.last_tool != -1:
            self._disable_feed_assist(self.last_tool)
            self.wait_ace_ready()
            if self.save_variables.allVariables.get('ace_filament_pos', FILAMENT_POS_UNKNOWN) == FILAMENT_POS_LOADED:
                self.ace_action = ACTION_CUTTING_FILAMENT
                self.gcode.run_script_from_command(self.cut_macros)
                self.filament_pos = FILAMENT_POS_IN_EXTRUDER
                self.save_variable('ace_filament_pos', self.filament_pos, True)
                self.ace_action = ACTION_IDLE

            if self.save_variables.allVariables.get('ace_filament_pos', FILAMENT_POS_UNKNOWN) == FILAMENT_POS_IN_EXTRUDER:
                self.ace_action = ACTION_UNLOADING_EXTRUDER
                self.filament_pos = FILAMENT_POS_EXTRUDER_ENTRY
                while bool(self.extruder_sensor.runout_helper.filament_present):
                    self._extruder_move(-20, self.extruder_move_speed)
                    self._retract(self.last_tool, 20, self.retract_speed)
                    self.wait_ace_ready()
                self.filament_pos = FILAMENT_POS_END_BOWDEN
                self.save_variable('ace_filament_pos', self.filament_pos, True)


            self.wait_ace_ready()

            self.ace_action = ACTION_UNLOADING
            self.filament_pos = FILAMENT_POS_IN_BOWDEN
            self._retract(self.last_tool, self.toolchange_retract_length, self.retract_speed)
            self.wait_ace_ready()
            self.filament_pos = FILAMENT_POS_UNLOADED

            self.save_variable('ace_filament_pos', self.filament_pos, True)
            self.ace_action = ACTION_IDLE
            if gate != -1:
                try:
                    self._park_to_toolhead(gate)
                except AceException as e:
                    self.ace_action = ACTION_IDLE
                    self.log_error(str(e))
                    return
        else:
            try:
                self._park_to_toolhead(gate)
            except AceException as e:
                self.ace_action = ACTION_IDLE
                self.log_error(str(e))
                return

        gcode_move = self.printer.lookup_object('gcode_move')
        gcode_move.reset_last_position()

        self.gcode.run_script_from_command('_ACE_POST_TOOLCHANGE FROM=' + str(self.last_tool) + ' TO=' + str(gate))
        gcode_move.reset_last_position()
        self.current_gate = gate
        self.save_variable('ace_current_index', gate, True)
        self.log_always("{2}Tool %s load{0}" % gate, True)
        self.last_tool = -1
        self.next_tool = -1
        self.save_variable('ace_filament_pos', self.filament_pos, True)

        now = self.reactor.monotonic()
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            is_printing = print_stats.get_status(now)["state"] == "printing"
        else:
            is_printing = self.printer.lookup_object("idle_timeout").get_status(now)["state"] == "Printing"

        if is_printing:
            self.num_toolchanges += 1


    def update_gate_map(self):
        self.save_variable('ace_gate_color', self.gate_color)
        self.save_variable('ace_gate_type', self.gate_material)
        self.save_variable('ace_gate_temp', self.gate_temp)
        self.save_variable('ace_gate_name', self.gate_name)
        self.save_variable('ace_gate_speed', self.gate_speed)
        self.save_variable('ace_gate_spool_id', self.gate_spool_id)
        self.write_variables()


    cmd_ACE_GATE_MAP_help = 'Set ace gate info'

    def cmd_ACE_GATE_MAP(self, gcmd):
        gate = gcmd.get_int('GATE', None)

        if gate is not None:
            color = gcmd.get('COLOR', None)
            material = gcmd.get('MATERIAL', None)
            name = gcmd.get('NAME', None)
            temp = gcmd.get_int('TEMP', None)
            speed = gcmd.get_int('SPEED', None)
            spool_id = gcmd.get_int('SPOOLID', None)

            if not color and not material and not temp and not name and not speed and not spool_id:
                gcmd.respond_info('ACE: Bad params')
                return
            if color is not None:
                self.gate_color[gate] = color
            if name is not None:
                self.gate_name[gate] = name
            if material is not None:
                self.gate_material[gate] = material
            if temp is not None:
                self.gate_temp[gate] = temp
            if speed is not None:
                self.gate_speed[gate] = speed
            if spool_id is not None:
                self.gate_spool_id[gate] = spool_id
            self.update_gate_map()
        else:
            gcmd.respond_info('ACE_MAP' + str(gate))

    cmd_ACE_ENDLESS_SPOOL_help = 'Enable/disable ace endless spool'

    def cmd_ACE_ENDLESS_SPOOL(self, gcmd):
        enable = gcmd.get_int('ENABLE', 1)
        self.save_variable('ace_endless_spool', bool(enable), True)

    cmd_ACE_DEBUG_help = 'ACE Debug'

    def cmd_ACE_DEBUG(self, gcmd):
        method = gcmd.get('METHOD')
        params = gcmd.get('PARAMS', '{}')

        try:
            def callback(self, response):
                self.gcode.respond_info(str(response))

            self.send_request(request={"method": method, "params": json.loads(params)}, callback=callback)
        except Exception as e:
            self.gcode.respond_info('Error: ' + str(e))

    def get_status(self, eventtime=None):

        return {
            'status': self._info['status'],
            'temp': self._info['temp'],
            'dryer_status': self._info['dryer_status'],
            'gate_status': self.gate_status,
        }


def load_config(config):
    return BunnyAce(config)

