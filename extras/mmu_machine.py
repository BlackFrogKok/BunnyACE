class MmuMachine:
    def __init__(self, config):
        pass

    def get_status(self, ev):
        return{"num_units":1,
               "unit_0":{
                   'name': 'Ace Pro',
                   'vendor':'Anycubic',
                   'version':'1.0',
                   'num_gates':4,
                   'first_gate':0,
                   'selector_type':'VirtualSelector',
                   'variable_rotation_distances':False,
                   'variable_bowden_lengths':False,
                   'require_bowden_move':False,
                   'filament_always_gripped':False,
                   'has_bypass':False,
                   'multi_gear':False,
               }
               }

def load_config(config):
    return MmuMachine(config)