import serial, threading, time, logging, json, struct, queue, traceback, re
from serial import SerialException
import serial.tools.list_ports

class MmuRunoutHelper:
    def __init__(self, printer, name, event_delay, insert_gcode, remove_gcode, runout_gcode, insert_remove_in_print, button_handler, switch_pin):

        self.printer, self.name = printer, name
        self.insert_gcode, self.remove_gcode, self.runout_gcode = insert_gcode, remove_gcode, runout_gcode
        self.insert_remove_in_print = insert_remove_in_print
        self.button_handler = button_handler
        self.switch_pin = switch_pin
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')

        self.min_event_systime = self.reactor.NEVER
        self.event_delay = event_delay # Time between generated events
        self.filament_present = False
        self.sensor_enabled = True
        self.runout_suspended = None
        self.button_handler_suspended = False

        self.printer.register_event_handler("klippy:ready", self._handle_ready)

        # Replace previous runout_helper mux commands with ours
        prev = self.gcode.mux_commands.get("QUERY_FILAMENT_SENSOR")
        _, prev_values = prev
        prev_values[self.name] = self.cmd_QUERY_FILAMENT_SENSOR

        prev = self.gcode.mux_commands.get("SET_FILAMENT_SENSOR")
        _, prev_values = prev
        prev_values[self.name] = self.cmd_SET_FILAMENT_SENSOR

    def _handle_ready(self):
        self.min_event_systime = self.reactor.monotonic() + 2. # Time to wait before first events are processed

    def _insert_event_handler(self, eventtime):
        self._exec_gcode("%s EVENTTIME=%s" % (self.insert_gcode, eventtime))

    def _remove_event_handler(self, eventtime):
        self._exec_gcode("%s EVENTTIME=%s" % (self.remove_gcode, eventtime))

    def _runout_event_handler(self, eventtime):
        # Pausing from inside an event requires that the pause portion of pause_resume execute immediately.
        pause_resume = self.printer.lookup_object('pause_resume')
        pause_resume.send_pause_command()
        self._exec_gcode("%s EVENTTIME=%s" % (self.runout_gcode, eventtime))

    def _exec_gcode(self, command):
        if command:
            try:
                self.gcode.run_script(command)
            except Exception:
                logging.exception("MMU: Error running mmu sensor handler: `%s`" % command)
        self.min_event_systime = self.reactor.monotonic() + self.event_delay

    # Latest klipper v0.12.0-462 added the passing of eventtime
    #     old: note_filament_present(self, is_filament_present):
    #     new: note_filament_present(self, eventtime, is_filament_present):
    def note_filament_present(self, *args):
        if len(args) == 1:
            eventtime = self.reactor.monotonic()
            is_filament_present = args[0]
        else:
            eventtime = args[0]
            is_filament_present = args[1]

        # Button handlers are used for sync feedback state switches
        if self.button_handler and not self.button_handler_suspended:
            self.button_handler(eventtime, is_filament_present, self)

        if is_filament_present == self.filament_present: return
        self.filament_present = is_filament_present

        # Don't handle too early or if disabled
        if eventtime >= self.min_event_systime and self.sensor_enabled:
            self._process_state_change(eventtime, is_filament_present)

    def _process_state_change(self, eventtime, is_filament_present):
        # Determine "printing" status
        now = self.reactor.monotonic()
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            is_printing = print_stats.get_status(now)["state"] == "printing"
        else:
            is_printing = self.printer.lookup_object("idle_timeout").get_status(now)["state"] == "Printing"

        if is_filament_present and self.insert_gcode: # Insert detected
            if not is_printing or (is_printing and self.insert_remove_in_print):
                self.min_event_systime = self.reactor.NEVER
                #logging.info("MMU: filament sensor %s: insert event detected, Eventtime %.2f" % (self.name, eventtime))
                self.reactor.register_callback(lambda reh: self._insert_event_handler(eventtime))

        else: # Remove or Runout detected
            self.min_event_systime = self.reactor.NEVER
            if is_printing and self.runout_suspended is False and self.runout_gcode:
                #logging.info("MMU: filament sensor %s: runout event detected, Eventtime %.2f" % (self.name, eventtime))
                self.reactor.register_callback(lambda reh: self._runout_event_handler(eventtime))
            elif self.remove_gcode and (not is_printing or self.insert_remove_in_print):
                # Just a "remove" event
                #logging.info("MMU: filament sensor %s: remove event detected, Eventtime %.2f" % (self.name, eventtime))
                self.reactor.register_callback(lambda reh: self._remove_event_handler(eventtime))

    def enable_runout(self, restore):
        self.runout_suspended = not restore

    def enable_button_feedback(self, restore):
        self.button_handler_suspended = not restore

    def get_status(self, eventtime):
        return {
            "filament_detected": bool(self.filament_present),
            "enabled": bool(self.sensor_enabled),
            "runout_suspended": bool(self.runout_suspended),
        }

    cmd_QUERY_FILAMENT_SENSOR_help = "Query the status of the Filament Sensor"
    def cmd_QUERY_FILAMENT_SENSOR(self, gcmd):
        if self.filament_present:
            msg = "MMU Sensor %s: filament detected" % (self.name)
        else:
            msg = "MMU Sensor %s: filament not detected" % (self.name)
        gcmd.respond_info(msg)

    cmd_SET_FILAMENT_SENSOR_help = "Sets the filament sensor on/off"
    def cmd_SET_FILAMENT_SENSOR(self, gcmd):
        self.sensor_enabled = bool(gcmd.get_int("ENABLE", 1))

class BunnyAce:
    VARS_ACE_REVISION = 'ace__revision'

    def __init__(self, config):
        self._connected = False
        self._serial = None
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self._name = config.get_name()
        self.lock = False
        self.send_time = None
        self.read_buffer = bytearray()
        if self._name.startswith('ace '):
            self._name = self._name[4:]

        self.save_variables = self.printer.lookup_object('save_variables', None)
        if self.save_variables:
            revision_var = self.save_variables.allVariables.get(self.VARS_ACE_REVISION, None)
            if revision_var is None:
                self.save_variables.allVariables[self.VARS_ACE_REVISION] = 0

        self.serial_id = config.get('serial', '/dev/ttyACM0')
        self.baud = config.getint('baud', 115200)
        extruder_sensor_pin = config.get('extruder_sensor_pin')
        toolhead_sensor_pin = config.get('toolhead_sensor_pin', None)
        self.feed_speed = config.getint('feed_speed', 50)
        self.retract_speed = config.getint('retract_speed', 50)
        self.toolchange_retract_length = config.getint('toolchange_retract_length', 100)
        self.toolhead_sensor_to_nozzle_length = config.getint('toolhead_sensor_to_nozzle', 0)
        self.poop_macros = config.get('poop_macros')
        self.cut_macros = config.get('cut_macros')
        extruder_sensor_pin = config.get('extruder_sensor_pin')

        # self.extruder_to_blade_length = config.getint('extruder_to_blade', None)

        self.max_dryer_temperature = config.getint('max_dryer_temperature', 55)

        self._callback_map = {}
        self._feed_assist_index = -1
        self._request_id = 0
        self.endstops = {}

        # Default data to prevent exceptions
        self.gate_status = ['empty', 'empty', 'empty', 'empty']
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
        self._create_mmu_sensor(config, extruder_sensor_pin, "extruder_sensor", self.extruder_sensor_handler)
        if toolhead_sensor_pin:
            self._create_mmu_sensor(config, toolhead_sensor_pin, "toolhead_sensor")

        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        self.printer.register_event_handler('klippy:disconnect', self._handle_disconnect)
        #self.printer.register_event_handler('klippy:shutdown', self._handle_disconnect)

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
            request['id'] = self._request_id
            self._request_id += 1

        payload = json.dumps(request)
        payload = bytes(payload, 'utf-8')

        data = bytes([0xFF, 0xAA])
        data += struct.pack('@H', len(payload))
        data += payload
        data += struct.pack('@H', self._calc_crc(payload))
        data += bytes([0xFE])
        self._serial.write(data)

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

    def _reader(self, eventtime):

        if self.lock and (self.reactor.monotonic() - self.send_time) > 2:
            self.lock = False
            self.read_buffer = bytearray()
            self.gcode.respond_info(f"timeout {self.reactor.monotonic()} {self._serial.isOpen()}")

        try:
            if self.lock:
                raw_bytes = self._serial.read(size=4096)
            else:
                raw_bytes = bytearray()
        except Exception:
            self.gcode.respond_info("Unable to communicate with the ACE PRO" + traceback.format_exc())
            self.lock = False
            self.gcode.respond_info('Try reconnecting')
            self._serial_disconnect()
            self.connect_timer = self.reactor.register_timer(self._connect, self.reactor.NOW)
            return self.reactor.NEVER

        if len(raw_bytes):
            text_buffer = self.read_buffer + raw_bytes
            i = text_buffer.find(b'\xfe')
            if i >= 0:
                buffer = text_buffer
                self.read_buffer = bytearray()
            else:
                self.read_buffer += raw_bytes
                return eventtime + 0.2
        else:
            return eventtime + 0.2

        if len(buffer) < 7:
            return eventtime + 0.2

        if buffer[0:2] != bytes([0xFF, 0xAA]):
            self.lock = False
            self.gcode.respond_info("Invalid data from ACE PRO (head bytes)")
            self.gcode.respond_info(str(buffer))
            return eventtime + 0.2

        payload_len = struct.unpack('<H', buffer[2:4])[0]
        #logging.info(str(buffer))
        payload = buffer[4:4 + payload_len]

        crc_data = buffer[4 + payload_len:4 + payload_len + 2]
        crc = struct.pack('@H', self._calc_crc(payload))

        if len(buffer) < (4 + payload_len + 2 + 1):
            self.lock = False
            self.gcode.respond_info(f"Invalid data from ACE PRO (len) {payload_len} {len(buffer)} {crc}")
            self.gcode.respond_info(str(buffer))
            return eventtime + 0.2

        if crc_data != crc:
            self.lock = False
            self.gcode.respond_info('Invalid data from ACE PRO (CRC)')

        ret = json.loads(payload.decode('utf-8'))
        id = ret['id']
        if id in self._callback_map:
            callback = self._callback_map.pop(id)
            callback(self=self, response=ret)
            self.lock = False
        return eventtime + 0.2

    def _writer(self, eventtime):
        try:
            def callback(self, response):
                if response is not None:
                    self._info = response['result']
                    self.gate_status = [data['status'] for data in self._info['slots']]

            if not self.lock:
                if not self._queue.empty():
                    task = self._queue.get()
                    if task is not None:
                        id = self._request_id
                        self._request_id += 1
                        self._callback_map[id] = task[1]
                        task[0]['id'] = id

                        self._send_request(task[0])
                        self.send_time = eventtime
                        self.lock = True
                else:
                    id = self._request_id
                    self._request_id += 1
                    self._callback_map[id] = callback
                    self._send_request({"id": id, "method": "get_status"})
                    self.send_time = eventtime
                    self.lock = True
        except Exception:
            logging.info('ACE error: ' + traceback.format_exc())
            self.lock = False
            self.gcode.respond_info('Try reconnecting')
            self._serial_disconnect()
            self.connect_timer = self.reactor.register_timer(self._connect, self.reactor.NOW)
            return self.reactor.NEVER
        return eventtime + 0.5

    def _handle_ready(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        logging.info('ACE: Connecting to ' + self.serial_id)
        # We can catch timing where ACE reboots itself when no data is available from host. We're avoiding it with this hack
        self._connected = False
        self._queue = queue.Queue()
        self._main_queue = queue.Queue()
        self.connect_timer = self.reactor.register_timer(self._connect, self.reactor.NOW)


    def _handle_disconnect(self):
        logging.info('ACE: Closing connection to ' + self.serial_id)
        self._serial.close()
        self._connected = False
        self.reactor.unregister_timer(self.writer_timer)
        self.reactor.unregister_timer(self.reader_timer)

        self._queue = None
        self._main_queue = None

    def dwell(self, delay = 1.):
        currTs = self.reactor.monotonic()
        self.reactor.pause(currTs + delay)

    def send_request(self, request, callback):
        self._info['status'] = 'busy'
        self._queue.put([request, callback])

    def wait_ace_ready(self):
        while self._info['status'] != 'ready':
            currTs = self.reactor.monotonic()
            self.reactor.pause(currTs + .5)

    def _extruder_move(self, length, speed):
        pos = self.toolhead.get_position()
        pos[3] += length
        self.toolhead.move(pos, speed)
        return pos[3]

    def extruder_sensor_handler(self, eventtime, is_filament_present, runout_helper):
        was_index = self.save_variables.allVariables.get('ace_current_index', -1)
        now = self.reactor.monotonic()
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            is_printing = print_stats.get_status(now)["state"] == "printing"
        else:
            is_printing = self.printer.lookup_object("idle_timeout").get_status(now)["state"] == "Printing"

        if (not is_filament_present) and self._info['slots'][was_index]['status'] == 'empty' and is_printing:
            ace_material = self.save_variables.allVariables.get('ace_gate_type')
            self.save_variable('ace_current_index', -1, True)
            pause_resume = self.printer.lookup_object('pause_resume')
            pause_resume.send_pause_command()

            if self.save_variables.allVariables.get('ace_endless_spool', False):
                self.gcode.respond_info('Endless spool')
                spools = list(filter(lambda x: x['status'] != 'empty'
                                               and ace_material[x['index']] == ace_material[was_index],
                                     self._info['slots']))
                self.gcode.respond_info(f'Change to spool: {spools[0]["index"]}')
                self.gcode.run_script_from_command(f'T{spools[0]["index"]}')
                pause_resume.send_resume_command()
            else:
                self.gcode.respond_info('Filament runout! Endless spool disabled')



    def _create_mmu_sensor(self, config, pin, name, handler=None):

        section = "filament_switch_sensor %s" % name
        config.fileconfig.add_section(section)
        config.fileconfig.set(section, "switch_pin", pin)
        config.fileconfig.set(section, "pause_on_runout", "False")
        fs = self.printer.load_object(config, section)

        ro_helper = MmuRunoutHelper(self.printer, name, 0.1, '', '', '',
                                    False, handler, pin)
        fs.runout_helper = ro_helper
        fs.get_status = ro_helper.get_status

        ppins = self.printer.lookup_object('pins')
        pin_params = ppins.parse_pin(pin, True, True)
        share_name = "%s:%s" % (pin_params['chip_name'], pin_params['pin'])
        ppins.allow_multi_use_pin(share_name)
        mcu_endstop = ppins.setup_pin('endstop', pin)

        query_endstops = self.printer.load_object(config, "query_endstops")
        query_endstops.register_endstop(mcu_endstop, share_name)
        self.endstops[name] = mcu_endstop

    def _check_endstop_state(self, name):
        print_time = self.toolhead.get_last_move_time()
        return bool(self.endstops[name].query_endstop(print_time))

    def _serial_disconnect(self):

        if self._serial is not None and self._serial.isOpen():
            self._serial.close()
            self._connected = False

        self.reactor.unregister_timer(self.reader_timer)
        self.reactor.unregister_timer(self.writer_timer)

    def _connect(self, eventtime):
        self.gcode.respond_info('Try connecting1')

        def info_callback(self, response):
            if 'msg' in response and response['msg'] != 'success':
                raise ValueError("ACE Error: " + response['msg'])
            self.gcode.respond_info(f"ACE: Connected to {response['result']['model']} \n "
                                    f"Firmware Version: {response['result']['firmware']}")

        try:
            self.gcode.respond_info('Try connecting')
            self._serial = serial.Serial(
                port=self.serial_id,
                baudrate=self.baud,
                timeout=0,
                write_timeout=0)

            if self._serial.isOpen():
                self._connected = True
                self._request_id = 0
                logging.info('ACE: Connected to ' + self.serial_id)
                self.writer_timer = self.reactor.register_timer(self._writer, eventtime + 2)
                self.reader_timer = self.reactor.register_timer(self._reader, eventtime + 2)
                self.send_request(request={"method": "get_info"},
                                  callback=lambda self, response: info_callback(self, response))
                if self._feed_assist_index != -1:
                    self._enable_feed_assist(self._feed_assist_index)
                self.reactor.unregister_timer(self.connect_timer)
                return self.reactor.NEVER
        except serial.serialutil.SerialException:
            self._serial = None
            logging.info('ACE: Conn error')
            self.gcode.respond_info('error')
        except Exception as e:
            self.gcode.respond_info(str(e))


        return eventtime + 1


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
                raise gcmd.error("ACE Error: " + response['msg'])

            self.gcode.respond_info('Started ACE drying')

        self.send_request(
            request={"method": "drying", "params": {"temp": temperature, "fan_speed": 7000, "duration": duration}},
            callback=callback)

    cmd_ACE_STOP_DRYING_help = 'Stops ACE Pro dryer'

    def cmd_ACE_STOP_DRYING(self, gcmd):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise gcmd.error("ACE Error: " + response['msg'])

            self.gcode.respond_info('Stopped ACE drying')

        self.send_request(request={"method": "drying_stop"}, callback=callback)

    def _enable_feed_assist(self, index):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise ValueError("ACE Error: " + response['msg'])
            else:
                self._feed_assist_index = index
                self.gcode.respond_info(str(response))

        self.send_request(request={"method": "start_feed_assist", "params": {"index": index}}, callback=callback)
        self.dwell(delay=0.7)

    cmd_ACE_ENABLE_FEED_ASSIST_help = 'Enables ACE feed assist'

    def cmd_ACE_ENABLE_FEED_ASSIST(self, gcmd):
        index = gcmd.get_int('INDEX')

        if index < 0 or index >= 4:
            raise gcmd.error('Wrong index')

        self._enable_feed_assist(index)

    def _disable_feed_assist(self, index):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise ValueError("ACE Error: " + response['msg'])

            self._feed_assist_index = -1
            self.gcode.respond_info('Disabled ACE feed assist')

        self.send_request(request={"method": "stop_feed_assist", "params": {"index": index}}, callback=callback)
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
                raise ValueError("ACE Error: " + response['msg'])

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
                raise ValueError("ACE Error: " + response['msg'])

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
                raise ValueError("ACE Error: " + response['msg'])


        self.send_request(
            request={"method": "update_feeding_speed", "params": {"index": index, "speed": speed}},
            callback=callback)

    def _stop_feeding(self, index):
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise ValueError("ACE Error: " + response['msg'])

        self.send_request(
            request={"method": "stop_feed_filament", "params": {"index": index}},
            callback=callback)

    def _park_to_toolhead(self, tool):

        sensor_extruder = self.printer.lookup_object("filament_switch_sensor %s" % "extruder_sensor", None)

        self.wait_ace_ready()

        self.save_variable('ace_filament_pos',"bowden", True)
        self._feed(tool, self.toolchange_retract_length + 200, self.retract_speed, self.toolchange_retract_length)
        self._set_feeding_speed(tool, 10)

        while not bool(sensor_extruder.runout_helper.filament_present):
            self.dwell(delay=0.1)

        self._stop_feeding(tool)

        self.wait_ace_ready()

        self._enable_feed_assist(tool)



        if not bool(sensor_extruder.runout_helper.filament_present):
            raise ValueError("Filament stuck " + str(bool(sensor_extruder.runout_helper.filament_present)))
        else:
            self.save_variable('ace_filament_pos', "spliter", True)

        if 'toolhead_sensor' in self.endstops:
            while not self._check_endstop_state('toolhead_sensor'):
                self._extruder_move(1, 5)
                self.dwell(delay=0.01)

        self.save_variable('ace_filament_pos', "toolhead", True)

        self._extruder_move(self.toolhead_sensor_to_nozzle_length, 5)
        self.save_variable('ace_filament_pos', "nozzle", True)

        gcode_move = self.printer.lookup_object('gcode_move')
        gcode_move.reset_last_position()
        self.gcode.run_script_from_command(self.poop_macros)

    cmd_ACE_CHANGE_TOOL_help = 'Changes tool'

    def cmd_ACE_CHANGE_TOOL(self, gcmd):
        tool = gcmd.get_int('TOOL')
        sensor_extruder = self.printer.lookup_object("filament_switch_sensor %s" % "extruder_sensor", None)

        if tool < -1 or tool >= 4:
            raise gcmd.error('Wrong tool')

        was = self.save_variables.allVariables.get('ace_current_index', -1)
        if was == tool:
            gcmd.respond_info('ACE: Not changing tool, current index already ' + str(tool))
            return

        if tool != -1:
            status = self._info['slots'][tool]['status']
            if status != 'ready':
                self.gcode.run_script_from_command('_ACE_ON_EMPTY_ERROR INDEX=' + str(tool))
                return
        self.gcode.run_script_from_command('_ACE_PRE_TOOLCHANGE FROM=' + str(was) + ' TO=' + str(tool))

        logging.info('ACE: Toolchange ' + str(was) + ' => ' + str(tool))
        if was != -1:
            self._disable_feed_assist(was)
            self.wait_ace_ready()
            if self.save_variables.allVariables.get('ace_filament_pos', "spliter") == "nozzle":
                self.gcode.run_script_from_command(self.cut_macros)
                self.save_variable('ace_filament_pos', "toolhead", True)

            if self.save_variables.allVariables.get('ace_filament_pos', "spliter") == "toolhead":
                while bool(sensor_extruder.runout_helper.filament_present):
                    self._extruder_move(-20, 10)
                    self._retract(was, 20, self.retract_speed)
                    self.wait_ace_ready()
                self.save_variable('ace_filament_pos', "bowden", True)

            self.wait_ace_ready()

            self._retract(was, self.toolchange_retract_length, self.retract_speed)
            self.wait_ace_ready()
            self.save_variable('ace_filament_pos', "spliter", True)

            if tool != -1:
                self._park_to_toolhead(tool)
        else:
            self._park_to_toolhead(tool)

        gcode_move = self.printer.lookup_object('gcode_move')
        gcode_move.reset_last_position()

        self.gcode.run_script_from_command('_ACE_POST_TOOLCHANGE FROM=' + str(was) + ' TO=' + str(tool))
        gcode_move.reset_last_position()
        self.save_variable('ace_current_index', tool, True)
        gcmd.respond_info(f"Tool {tool} load")

    cmd_ACE_GATE_MAP_help ='Set ace gate info'
    def cmd_ACE_GATE_MAP(self, gcmd):
        gate = gcmd.get_int('GATE', None)

        if gate is not None:
            color = gcmd.get('COLOR', None)
            type = gcmd.get('TYPE', None)
            temp = gcmd.get_int('TEMP', None)
            if not color and not type and not temp:
                gcmd.respond_info('ACE: Bad params')
                return
            if color is not None:
                self.save_variables.allVariables['ace_gate_color'][gate] = color
            if type is not None:
                self.save_variables.allVariables['ace_gate_type'][gate] = type
            if temp is not None:
                self.save_variables.allVariables['ace_gate_temp'][gate] = temp
            self.write_variables()
        else:
            gcmd.respond_info('ACE_MAP' + str(gate))


    cmd_ACE_ENDLESS_SPOOL_help = 'Enable/disable ace endless spool'
    def cmd_ACE_ENDLESS_SPOOL(self, gcmd):
        enable = gcmd.get_int('ENABLE', 1)
        self.save_variable('ace_endless_spool', bool(enable), True)

    def cmd_ACE_DEBUG(self, gcmd):
        #self.gcode.respond_info(str(self._info))
        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise ValueError("ACE Error: " + response['msg'])

        self.send_request(
            request={"method": "unwind_filament", "params": {"index": 0, "length": 100, "speed": 25, "mode": 1}},
            callback=callback)


    def get_status(self, eventtime=None):

        return {
            'temp': self._info['temp'],
            'dryer_status': self._info['dryer_status'],
            'gate_color': list(self.save_variables.allVariables.get('ace_gate_color')),
            'gate_material': list(self.save_variables.allVariables.get('ace_gate_type')),
            'gate_temp': list(self.save_variables.allVariables.get('ace_gate_temp')),
            'active_gate': self.gate_status,
            'spool_id': [1, 1, 1, 2],
            'selected_gate': int(self.save_variables.allVariables.get('ace_current_index', -1)),
            'endless_spool': bool(self.save_variables.allVariables.get('ace_endless_spool', False)),
        }



def load_config(config):
    return BunnyAce(config)
