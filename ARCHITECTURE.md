# ViscoLogic Architecture - Actual Implementation

This document describes how modules actually work together based on the real codebase.

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      app.py (Entry Point)                    │
│  - Builds all components                                     │
│  - Starts orchestrator, modbus, UI                          │
│  - Handles graceful shutdown                                 │
└───────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
┌───────▼────────┐            ┌────────▼────────┐
│  EventBus      │            │  ConfigManager   │
│  (Central Hub) │            │  (Settings)      │
└───────┬────────┘            └─────────────────┘
        │
        │ publish_frame() / subscribe_frames()
        │ push_command() / pop_command()
        │
┌───────┴──────────────────────────────────────────┐
│                                                    │
│  ┌────────────────────────────────────────────┐  │
│  │         Orchestrator (Core Engine)         │  │
│  │  - Runs in separate thread                  │  │
│  │  - Coordinates all subsystems              │  │
│  │  - Main measurement loop                    │  │
│  └───────┬────────────────────────────────────┘  │
│          │                                        │
│    ┌─────┴─────┬──────────┬──────────┬────────┐ │
│    │           │          │          │        │ │
│  ┌─▼─┐    ┌───▼──┐  ┌────▼───┐ ┌───▼──┐ ┌───▼┐│
│  │SM │    │Safety│  │Drivers │ │ DSP  │ │Model││
│  └───┘    └──────┘  └────────┘ └──────┘ └─────┘│
│                                                    │
│  ┌────────────────────────────────────────────┐  │
│  │         UI Layer (Tkinter)                 │  │
│  │  - OperatorScreen                           │  │
│  │  - EngineerScreen                           │  │
│  │  - AlarmsScreen                             │  │
│  │  - CalibrationWizard                        │  │
│  │  - CommissioningWizard                      │  │
│  └────────────────────────────────────────────┘  │
│                                                    │
│  ┌────────────────────────────────────────────┐  │
│  │         Modbus Server                       │  │
│  │  - PLC communication                        │  │
│  └────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

## Component Initialization Flow

### 1. app.py → build_context()

```python
1. Setup logging
2. Load config (ConfigManager or fallback)
3. Create EventBus
4. Create SqliteStore (if available)
5. Create Orchestrator(config, bus, logger)
6. Create ModbusServer(config, bus, logger)
7. Create MainWindowApp(config, bus, logger)
8. Return AppContext
```

### 2. Orchestrator.__init__()

```python
1. Initialize SQLite store
2. Create subsystems:
   - SystemStateMachine (sm)
   - SafetyManager (safety)
   - Diagnostics (diag)
   - CommissioningManager (commissioning)
3. Create drivers:
   - ADS1115ADC (adc)
   - MAX31865Temp (temp)
   - DrivePWM (drive)
4. Create DSP modules:
   - LockInIQ (lockin)
   - SweepTracker (sweep)
   - HealthScorer (health)
5. Create model:
   - CalibrationStore (cal_store)
   - CalibrationLUT (cal_lut)
   - ViscosityCompute (visc_compute)
   - TempCompensation (temp_comp)
6. Create storage:
   - CsvLogger (csv)
   - RetentionManager (retention)
7. Wire event bus subscriptions
8. Start thread loop
```

### 3. MainWindowApp.__init__()

```python
1. Initialize backend (storage, auth, calibration)
2. Setup window
3. Build status bar
4. Create screen stack:
   - OperatorScreen
   - EngineerScreen
   - AlarmsScreen
   - CalibrationWizard
   - CommissioningWizard
   - CommissioningLock
5. Decide startup screen (commissioned check)
6. Subscribe to event bus
7. Start polling loop
```

## Data Flow

### Measurement Data Flow (Orchestrator → UI)

```
Orchestrator._tick() (every loop iteration)
  │
  ├─> Read ADC (adc.read())
  ├─> Read Temp (temp.read())
  ├─> Compute drive (sweep/lockin)
  ├─> Apply drive (drive.set_freq_duty())
  ├─> Process signal (lockin.update())
  ├─> Compute viscosity (visc_compute.compute())
  ├─> Create RuntimeSnapshot
  │
  └─> bus.publish_frame(snapshot_dict)
      │
      ├─> EventBus stores in _latest_frame
      ├─> EventBus notifies subscribers (subscribe_frames callbacks)
      │
      └─> UI screens receive:
          ├─> OperatorScreen._on_frame_event()
          ├─> EngineerScreen._on_frame() (via subscribe_frames)
          └─> Or via polling: bus.get_latest_frame()
```

### Command Flow (UI → Orchestrator)

```
UI Screen (e.g., OperatorScreen)
  │
  └─> _send_cmd("START")
      │
      └─> bus.publish("ui.command", {"cmd": "START", "source": "local"})
          │
          └─> Orchestrator._wire_bus() subscribed to "ui.command"
              │
              └─> _handle_ui_command(payload)
                  │
                  └─> sm.handle_event("START", {...})
                      │
                      └─> StateMachine transitions state
```

### Modbus Flow (PLC ↔ Orchestrator)

```
PLC (Modbus Client)
  │
  ├─> Reads registers (40001-40009)
  │   └─> ModbusServer.read_callback()
  │       └─> Reads from RegisterBank
  │           └─> RegisterBank populated by Orchestrator
  │
  └─> Writes command (41004: CMD_WORD, 41005: CMD_SEQ)
      └─> ModbusServer.write_callback()
          └─> bus.push_command(source="PLC", cmd_type="START", ...)
              │
              └─> Orchestrator._poll_modbus_commands()
                  └─> bus.pop_command()
                      └─> Process command (same as UI commands)
```

## Event Bus Pattern

### EventBus Responsibilities

1. **Frame Publishing** (Measurement Data)
   - `publish_frame(frame_dict)` - Called by Orchestrator
   - Stores in `_latest_frame` (thread-safe)
   - Notifies subscribers via callbacks
   - `get_latest_frame()` - For polling fallback

2. **Command Queue** (UI/PLC → Orchestrator)
   - `push_command(source, cmd_type, payload)` - Called by UI/Modbus
   - Thread-safe queue
   - `pop_command()` - Called by Orchestrator
   - `drain_commands()` - Batch processing

3. **Subscriptions**
   - `subscribe_frames(callback)` - For real-time frame updates
   - `subscribe(topic, callback)` - Generic topic subscriptions

### How UI Screens Connect

**OperatorScreen:**
```python
# Tries generic subscribe first
bus.subscribe("frame", self._on_frame_event)
bus.subscribe("ui.frame", self._on_frame_event)

# Also polls as fallback
bus.get_latest_frame() or bus.latest_frame
```

**EngineerScreen:**
```python
# Preferred: EventBus standard method
bus.subscribe_frames(self._on_frame)

# Fallback: Generic subscribe
bus.subscribe("frame", self._on_frame)
bus.subscribe("ui.frame", self._on_frame)

# Always polls as backup
bus.get_latest_frame()
```

## Orchestrator Main Loop

```python
def _run_loop(self):
    while not self._stop.is_set():
        dt = calculate_dt()
        self._tick(dt)  # Main processing
        time.sleep(0.01)  # ~100Hz loop
```

### _tick() Sequence

1. **Read PLC Commands** (if remote enabled)
   - `_poll_modbus_commands()`

2. **Read Hardware**
   - `_read_temperature()` → temp_c, temp_fault
   - `_read_adc()` → adc_val

3. **State Machine Tick**
   - `sm.tick({"dt": dt, "ts": ts})`

4. **Compute Drive**
   - `_compute_drive_setpoints()` → freq_hz, duty
   - Based on state: SWEEPING, LOCKING, or LOCKED

5. **Apply Drive**
   - `_apply_drive(freq_hz, duty)`

6. **DSP Processing**
   - `lockin.update(adc_val)` → magnitude, phase
   - If SWEEPING: `sweep.submit_point(freq, mag)`

7. **Compute Viscosity**
   - `_compute_viscosity(mag, temp_c)` → viscosity_cp

8. **Safety Check**
   - `_check_safety(temp_c, duty)` → fault_reason

9. **Health Score**
   - `health.compute(...)` → health_score

10. **Create Snapshot**
    - Build `RuntimeSnapshot` dataclass
    - Convert to dict with extra fields

11. **Publish Frame**
    - `bus.publish_frame(snapshot_dict)`

12. **Logging** (best-effort)
    - CSV logger
    - SQLite (if enabled)

13. **Modbus Update**
    - Update RegisterBank with latest values

## State Machine Flow

```
BOOT → SELF_CHECK → IDLE → SWEEPING → LOCKING → RUNNING
                                              ↓
                                          FAULT (if error)
```

**Key Events:**
- `START` → IDLE → SWEEPING
- `SWEEP_DONE` → SWEEPING → LOCKING
- `LOCK_ACQUIRED` → LOCKING → RUNNING
- `STOP` → Any state → IDLE
- `FAULT` → Any state → FAULT

## Module Dependencies

```
Orchestrator depends on:
  - StateMachine (state transitions)
  - SafetyManager (fault detection)
  - Diagnostics (self-check)
  - Drivers (ADC, Temp, PWM)
  - DSP (LockIn, Sweep, Health)
  - Model (Calibration, ViscosityCompute)
  - Storage (SQLite, CSV)
  - EventBus (publish frames, read commands)

UI depends on:
  - EventBus (receive frames, send commands)
  - ConfigManager (read settings)
  - CommissioningManager (check commissioned)
  - AuthEngineer (password verification)
  - CalibrationStore (calibration data)

Modbus depends on:
  - EventBus (push commands, read frames)
  - RegisterBank (register mapping)
  - Orchestrator (indirectly, via bus)
```

## Thread Safety

- **EventBus**: Thread-safe (locks on frame/command queues)
- **Orchestrator**: Runs in separate thread
- **UI**: Main thread (Tkinter)
- **Modbus**: Separate thread (if async server)

**Communication:**
- UI → Orchestrator: EventBus command queue (thread-safe)
- Orchestrator → UI: EventBus frame publishing (thread-safe)
- Both can poll `get_latest_frame()` safely

## Key Design Patterns

1. **Dependency Injection**: All components receive dependencies via constructor
2. **Event-Driven**: EventBus decouples components
3. **State Machine**: Centralized state management
4. **Observer Pattern**: Frame subscribers notified on updates
5. **Command Pattern**: Commands queued and processed asynchronously
6. **Fallback Pattern**: Safe fallbacks if modules unavailable

## Configuration Flow

```
settings.yaml
  │
  └─> ConfigManager.load()
      │
      └─> Validated config dict
          │
          ├─> Orchestrator uses for all subsystems
          ├─> UI uses for display settings
          └─> Modbus uses for server config
```

## Storage Architecture

```
SQLite (viscologic.db)
  ├─> device_state (commissioned flag, etc.)
  ├─> calibration_profiles
  ├─> calibration_points
  └─> events (alarms, state changes)

CSV Logger
  └─> Daily files: timestamp, viscosity, temp, freq, health, status, alarms

Retention Manager
  └─> Auto-deletes old data based on config
```

