

class Mmu:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.ace = self.printer.lookup_object('ace')

        self.reactor = self.printer.get_reactor()

        self.endless = [0,0,0,0]

        self.gcode.register_command(
            'MMU_SELECT', self.cmd_MMU_SELECT,
            desc="a")

        self.gcode.register_command(
            'MMU_GATE_MAP', self.cmd_MMU_GATE_MAP,
            desc="a")

        self.gcode.register_command(
            'MMU_REMAP_TTG', self.cmd_MMU_REMAP_TTG,
            desc="a")

        self.gcode.register_command(
            'MMU_SYNC_GEAR_MOTOR', self.cmd_MMU_SYNC_GEAR_MOTOR,
            desc="a")

        self.gcode.register_command(
            'MMU_ENDLESS_SPOOL', self.cmd_MMU_ENDLESS_SPOOL,
            desc="a")

        self.gcode.register_command(
            'MMU_LOAD', lambda x: x,
            desc="a")

        self.gcode.register_command(
            'MMU_UNLOAD', self.cmd_MMU_UNLOAD,
            desc="a")

    def cmd_MMU_SELECT(self, gcmd):
        self.ace.cmd_ACE_CHANGE_TOOL(gcmd)

    def cmd_MMU_GATE_MAP(self, gcmd):
        self.ace.cmd_ACE_GATE_MAP(gcmd)

    def cmd_MMU_REMAP_TTG(self, gcmd):
        self.ace.cmd_ACE_TTG_MAP(gcmd)

    def cmd_MMU_UNLOAD(self, gcmd):
        Tgcmd = self.gcode.create_gcode_command("ACE_CHANGE_TOOL", "ACE_CHANGE_TOOL", {'GATE':-1})
        self.ace.cmd_ACE_CHANGE_TOOL(Tgcmd)

    def cmd_MMU_SYNC_GEAR_MOTOR(self, gcmd):
        sync = gcmd.get_int('SYNC', None)

        if sync:
            self.ace._enable_feed_assist(self.ace.current_gate)
        else:
            self.ace._disable_feed_assist()

    def cmd_MMU_ENDLESS_SPOOL(self, gcmd):
        self.endless = gcmd.get('GROUPS', ",".join(map(str, self.endless))).split(",")

    def get_status(self, eventtime):
        gate_vendor = ['НИТ1', 'НИТ2', 'НИТ3', 'НИТ4']

        print_stats = self.printer.lookup_object("print_stats", None)


        return {
                'enabled':True,
                'num_gates': 4,
                'print_state': 'started' if print_stats.get_status(eventtime)['state'] != 'printing' else 'printing',
                'gate': self.ace.current_gate,
                'tool': self.ace.ttg_map[self.ace.current_gate] if self.ace.current_gate != -1 else -1,
                'active_filament':{
                    'empty': not bool(self.ace.gate_status[self.ace.current_gate]),
                    'vendor': gate_vendor[self.ace.current_gate],
                    'material': self.ace.gate_material[self.ace.current_gate],
                    'color': self.ace.gate_color[self.ace.current_gate],
                    'manufacturer': gate_vendor[self.ace.current_gate]
                },
                'num_toolchanges': self.ace.num_toolchanges,
                'last_tool': self.ace.last_tool,
                'next_tool': self.ace.next_tool,
                'filament': self.ace.gate_name[self.ace.current_gate],  # Calculated from current gate
                "filament_position": 0,
                'filament_pos': self.ace.filament_pos,  # Calculated based on gate status
                'ttg_map': list(self.ace.ttg_map),
                'endless_spool_groups':self.endless,
                'gate_status': list(self.ace.gate_status),
                'gate_filament_name': list(self.ace.gate_name),
                'gate_material': list(self.ace.gate_material),
                'gate_color': list(self.ace.gate_color),
                'gate_temperature': list(self.ace.gate_temp),
                'gate_spool_id': self.ace.gate_spool_id,
                'gate_speed_override': self.ace.gate_speed,
                'gate_vendor': gate_vendor,
                'slicer_tool_map': {'tools':[]},
                'action': self.ace.ace_action,
                'has_bypass': False,
                'sync_drive': (self.ace._feed_assist_index != -1),
                'sync_feedback_enabled': False,
                'clog_detection_enabled': False,
                'endless_spool_enabled': True,  # Enable endless spool for backup roll functionality
                'reason_for_pause': self.ace.error_msg,
                'spoolman_support': "readonly",  # off/readonly/push/pull - we don't use spoolman
                'sensors':{
                    'extruder': bool(self.ace.extruder_sensor.runout_helper.filament_present)
                },
        }

def load_config(config):
    return Mmu(config)


