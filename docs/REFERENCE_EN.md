# BunnyACE - Technical Documentation

## System Overview

**BunnyACE** is a Klipper-based module for 3D printers designed to control the ACE Pro multi-material filament management system. The system provides automatic tool changing, filament drying, material feed control, and "endless spool" technology support.

## System Architecture

### Core Components

1. **MmuRunoutHelper** - Helper for handling filament runout events
2. **BunnyAce** - Main control class for ACE Pro system

### Communication and Data Protocol

- **Serial Interface**: Communication via UART/USB
- **Protocol**: JSON over serial port with CRC integrity check
- **Baud Rate**: Default 115200 baud

## Configuration Parameters

### Required Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `serial` | string | Serial port path | `/dev/ttyACM0` |
| `extruder_sensor_pin` | string | Extruder filament sensor pin | `^gpio21` |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `baud` | integer | 115200 | Serial port baud rate |
| `toolhead_sensor_pin` | string | None | Toolhead filament sensor pin |
| `feed_speed` | integer | 50 | Filament feed speed (mm/s) |
| `retract_speed` | integer | 50 | Filament retract speed (mm/s) |
| `toolchange_retract_length` | integer | 100 | Retract length during tool change (mm) |
| `toolhead_sensor_to_nozzle` | integer | 0 | Distance from toolhead sensor to nozzle (mm) |
| `max_dryer_temperature` | integer | 55 | Maximum dryer temperature (°C) |
| `poop_macros` | string | - | G-code macro for nozzle purging |
| `cut_macros` | string | - | G-code macro for filament cutting |

## G-code Commands

### ACE_START_DRYING
**Purpose**: Starts the filament drying process in ACE Pro

**Syntax**: `ACE_START_DRYING TEMP=<temperature> [DURATION=<time>]`

**Parameters**:
- `TEMP` (required) - drying temperature (1-55°C)
- `DURATION` (optional) - drying time in minutes (default: 240)

**Example**: `ACE_START_DRYING TEMP=45 DURATION=180`

### ACE_STOP_DRYING
**Purpose**: Stops the filament drying process

**Syntax**: `ACE_STOP_DRYING`

**Parameters**: None

### ACE_ENABLE_FEED_ASSIST
**Purpose**: Enables feed assist for the specified slot

**Syntax**: `ACE_ENABLE_FEED_ASSIST INDEX=<slot_number>`

**Parameters**:
- `INDEX` (required) - slot number (0-3)

**Example**: `ACE_ENABLE_FEED_ASSIST INDEX=0`

### ACE_DISABLE_FEED_ASSIST
**Purpose**: Disables feed assist

**Syntax**: `ACE_DISABLE_FEED_ASSIST [INDEX=<slot_number>]`

**Parameters**:
- `INDEX` (optional) - slot number (0-3), if not specified, uses current active

### ACE_FEED
**Purpose**: Feeds filament from the specified slot for the given length

**Syntax**: `ACE_FEED INDEX=<slot_number> LENGTH=<length> [SPEED=<speed>]`

**Parameters**:
- `INDEX` (required) - slot number (0-3)
- `LENGTH` (required) - feed length in mm (>0)
- `SPEED` (optional) - feed speed in mm/s (default: `feed_speed` value)

**Example**: `ACE_FEED INDEX=0 LENGTH=100 SPEED=25`

### ACE_RETRACT
**Purpose**: Retracts filament back to ACE Pro

**Syntax**: `ACE_RETRACT INDEX=<slot_number> LENGTH=<length> [SPEED=<speed>]`

**Parameters**:
- `INDEX` (required) - slot number (0-3)
- `LENGTH` (required) - retract length in mm (>0)
- `SPEED` (optional) - retract speed in mm/s (default: `retract_speed` value)

**Example**: `ACE_RETRACT INDEX=1 LENGTH=50 SPEED=30`

### ACE_CHANGE_TOOL
**Purpose**: Performs tool (filament) change

**Syntax**: `ACE_CHANGE_TOOL TOOL=<tool_number>`

**Parameters**:
- `TOOL` (required) - tool number (-1 to unload, 0-3 to load)

**Example**: `ACE_CHANGE_TOOL TOOL=2`

### ACE_GATE_MAP
**Purpose**: Configures filament parameters for the specified slot

**Syntax**: `ACE_GATE_MAP GATE=<slot_number> [COLOR=<color>] [TYPE=<type>] [TEMP=<temperature>]`

**Parameters**:
- `GATE` (required) - slot number (0-3)
- `COLOR` (optional) - filament color
- `TYPE` (optional) - material type (PLA, PETG, ABS, etc.)
- `TEMP` (optional) - printing temperature

**Example**: `ACE_GATE_MAP GATE=0 COLOR=red TYPE=PLA TEMP=210`

### ACE_ENDLESS_SPOOL
**Purpose**: Enables or disables "endless spool" mode

**Syntax**: `ACE_ENDLESS_SPOOL [ENABLE=<value>]`

**Parameters**:
- `ENABLE` (optional) - 1 to enable, 0 to disable (default: 1)

**Example**: `ACE_ENDLESS_SPOOL ENABLE=1`

### ACE_DEBUG
**Purpose**: Debug command for system testing

**Syntax**: `ACE_DEBUG`

**Parameters**: None

**Description**: Performs test filament retraction from slot 0

## System Methods

### Utility Functions

#### _calc_crc(buffer)
**Purpose**: Calculates CRC checksum for data integrity verification

**Parameters**:
- `buffer` - data buffer for CRC calculation

**Returns**: 16-bit checksum

#### _send_request(request)
**Purpose**: Sends JSON request to ACE Pro via serial interface

**Parameters**:
- `request` - dictionary with request data

**Packet Protocol**:
```
[0xFF 0xAA] [length] [JSON payload] [CRC] [0xFE]
```

### Connection Management

#### _connect()
**Purpose**: Establishes connection with ACE Pro device

**Features**:
- Automatic reconnection on failure
- Device firmware information retrieval
- Active feed assist functions restoration

#### _serial_disconnect()
**Purpose**: Disconnects from device

**Actions**:
- Serial port closure
- Read/write timer stopping
- Connection flags reset

### Sensor Handling

#### extruder_sensor_handler(eventtime, is_filament_present, runout_helper)
**Purpose**: Handles extruder filament sensor events

**Functions**:
- Filament runout detection during printing
- "Endless spool" mode activation
- Automatic print pause on material runout
- Compatible material search and loading

**"Endless Spool" Logic**:
1. Filament runout detection
2. Compatible material slot search
3. Automatic tool change
4. Print continuation

### Internal Control Methods

#### _extruder_move(length, speed)
**Purpose**: Moves extruder by specified distance

**Parameters**:
- `length` - distance in mm (can be negative for retraction)
- `speed` - movement speed in mm/s

#### _park_to_toolhead(tool)
**Purpose**: Feeds filament from ACE to toolhead

**Stages**:
1. Filament feeding through Bowden tube
2. Filament detection by extruder sensor
3. Feed assist activation for precise feeding
4. Advancement to toolhead sensor (if present)
5. Final feed to nozzle

#### wait_ace_ready()
**Purpose**: Waits for ACE system readiness to execute commands

**Logic**: Blocks execution until `ready` status received

## System States

### Slot Statuses
- `empty` - slot is empty, no filament
- `ready` - filament loaded and ready for use
- `busy` - slot in operation process

### Filament Positions
System tracks current filament position:
- `spliter` - filament in ACE splitter
- `bowden` - filament in Bowden tube
- `toolhead` - filament in toolhead
- `nozzle` - filament reached nozzle

### Dryer Statuses
- `stop` - dryer stopped
- `running` - drying process active

**Drying Parameters**:
- `target_temp` - target temperature
- `duration` - total drying time
- `remain_time` - remaining time

### System Information
```json
{
  "status": "ready|busy",
  "temp": 25,
  "fan_speed": 7000,
  "enable_rfid": 1,
  "slots": [
    {
      "index": 0,
      "status": "ready|empty|busy",
      "sku": "material_code",
      "type": "PLA",
      "color": [255, 0, 0]
    }
  ]
}
```

## Error Handling

### Error Types

#### Communication Errors
- **Connection timeout**: Automatic reconnection after 1 second
- **CRC errors**: Packet resend
- **Connection loss**: Switch to reconnection mode

#### Parameter Validation Errors
- **Invalid slot index**: Must be 0-3
- **Invalid temperature**: 1-55°C for dryer
- **Invalid speed**: Must be >0
- **Invalid length**: Must be >0

#### Device Errors
- **Empty slot**: Attempt to load from empty slot
- **Blocked filament**: Filament stuck in system
- **Dryer errors**: Overheat or malfunction

### Recovery Mechanisms

#### Automatic Reconnection
```python
def _connect(self, eventtime):
    # Connection attempt every second
    # Active functions restoration
    # Firmware version check
```

#### Callback Handling
```python
def callback(self, response):
    if 'code' in response and response['code'] != 0:
        raise ValueError("ACE Error: " + response['msg'])
    # Successful response handling
```

## Klipper Integration

### System Events
- `klippy:ready` - initialization after Klipper startup
- `klippy:disconnect` - proper closure on shutdown

### Variable Persistence
System uses `save_variables` module for persistent storage:

#### State Variables
- `ace_current_index` - current active tool (-1 if none)
- `ace_filament_pos` - filament position (spliter/bowden/toolhead/nozzle)
- `ace_endless_spool` - endless spool mode state

#### Configuration Variables
- `ace_gate_color` - array of filament colors by slots
- `ace_gate_type` - array of material types by slots
- `ace_gate_temp` - array of printing temperatures by slots

#### System Variables
- `ace__revision` - configuration version for change tracking

### Supported Macros

#### Required Macros
These macros must be defined in configuration:

**`_ACE_PRE_TOOLCHANGE FROM=<old> TO=<new>`**
- Executed before tool change starts
- May contain preparation logic (e.g., axis parking)

**`_ACE_POST_TOOLCHANGE FROM=<old> TO=<new>`**
- Executed after tool change completion
- May contain finalization logic (e.g., pressure calibration)

**`_ACE_ON_EMPTY_ERROR INDEX=<slot>`**
- Called when attempting to load from empty slot
- Allows custom error handling implementation

#### Configuration Macros
Specified in configuration parameters:

**`poop_macros`** - nozzle purge macro
- Executed after new filament loading
- Usually includes material extrusion for cleaning

**`cut_macros`** - filament cutting macro
- Executed when changing from "nozzle" position
- May use mechanical or thermal cutting

### Sensor Integration

#### Extruder Sensor
```python
[filament_switch_sensor extruder_sensor]
switch_pin: ^gpio21
pause_on_runout: False
```

#### Toolhead Sensor (optional)
```python
[filament_switch_sensor toolhead_sensor]
switch_pin: ^gpio22
pause_on_runout: False
```

### Status Object for Mainsail/Fluidd

System provides status via `get_status()` method:

```python
{
    'temp': 25,                    # Current temperature
    'dryer_status': {...},         # Dryer status
    'gate_color': ['red', 'blue'], # Colors by slots
    'gate_material': ['PLA', 'PETG'], # Materials
    'gate_temp': [210, 240],       # Printing temperatures
    'active_gate': ['ready', 'empty'], # Slot statuses
    'selected_gate': 0,            # Active slot
    'endless_spool': True          # Endless spool status
}
```

## Configuration Examples

### Minimal Configuration
```ini
[ace]
serial: /dev/ttyACM0
extruder_sensor_pin: ^gpio21
poop_macros: PRIME_NOZZLE
cut_macros: CUT_FILAMENT
```

### Extended Configuration
```ini
[ace]
serial: /dev/ttyACM0
baud: 115200
extruder_sensor_pin: ^gpio21
toolhead_sensor_pin: ^gpio22
feed_speed: 25
retract_speed: 30
toolchange_retract_length: 120
toolhead_sensor_to_nozzle: 50
max_dryer_temperature: 60
poop_macros: PRIME_NOZZLE TEMP={material_temp}
cut_macros: CUT_FILAMENT RETRACT=5
```

### Macro Examples
```gcode
[gcode_macro PRIME_NOZZLE]
gcode:
    G1 E20 F300        # Extrude 20mm for purging
    G1 E-2 F1800       # Small retraction

[gcode_macro CUT_FILAMENT]
gcode:
    G1 E-5 F1800       # Retract before cutting
    # Cutter activation logic

[gcode_macro _ACE_PRE_TOOLCHANGE]
gcode:
    SAVE_GCODE_STATE NAME=toolchange
    G28 X Y            # Park axes

[gcode_macro _ACE_POST_TOOLCHANGE]
gcode:
    RESTORE_GCODE_STATE NAME=toolchange
    # Additional calibration if needed
```

## Troubleshooting

### Connection Issues
**Symptom**: `Unable to communicate with the ACE PRO`
**Solution**:
1. Verify correct port path
2. Ensure device is connected
3. Check port access permissions
4. Restart Klipper

### Filament Issues
**Symptom**: `Filament stuck`
**Solution**:
1. Check sensor connections are correct
2. Ensure no blockages in Bowden tube
3. Verify movement length calibration

### Dryer Issues
**Symptom**: Temperature errors
**Solution**:
1. Check `max_dryer_temperature` setting
2. Ensure temperature doesn't exceed limit
3. Verify temperature sensor functionality

---

**Documentation Version**: 1.0
**Compatibility**: Klipper 0.11.0+, ACE Pro Firmware 1.0+
**Created**: 2024
