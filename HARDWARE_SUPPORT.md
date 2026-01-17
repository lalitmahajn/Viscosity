# Hardware Support Analysis

## Current State

### ✅ **Hardware Detection**
All three drivers (`adc_ads1115.py`, `drive_pwm.py`, `temp_max31865.py`) support real hardware with automatic fallback to mocks:

1. **ADC Driver (ADS1115)**:
   - Uses Adafruit CircuitPython library
   - Connects via I2C (configurable bus and address)
   - Falls back to mock if hardware unavailable

2. **Drive PWM Driver**:
   - Uses `pigpio` library for Raspberry Pi GPIO
   - Requires `pigpiod` daemon running
   - Falls back to mock if pigpio unavailable

3. **Temperature Driver (MAX31865)**:
   - Uses Adafruit CircuitPython library
   - Connects via SPI (configurable CS pin)
   - Falls back to mock if hardware unavailable

### ✅ **Hot-Plug Support (NEW)**

**Current Behavior:**
- Hardware is detected **at first use** (lazy initialization)
- If hardware is **not available at startup**, driver falls back to **mock mode**
- **NEW**: All drivers now support `reinitialize()` method to detect hardware after startup
- **Usage**: Call `driver.reinitialize()` to attempt reconnection to hardware

**Example:**
```python
# Check if hardware is now available
success, message = orchestrator.adc.reinitialize()
if success:
    print(f"Hardware detected: {message}")
else:
    print(f"Still using mock: {message}")
```

### 🔧 **How It Works**

```python
def _ensure_open(self):
    if self._ads is not None:  # Already initialized
        return
    
    try:
        # Try real hardware
        self._ads = ADS.ADS1115(i2c, ...)
    except Exception:
        # Fall back to mock
        self._ads = _MockChan(...)
```

Once `self._ads` is set (either real or mock), it never changes.

## Reinitialization API

### ✅ **Implemented: `reinitialize()` Method**

All three drivers now support hardware reinitialization:

**ADC Driver:**
```python
success, message = adc.reinitialize()
# Returns: (bool, str) - success status and message
```

**Drive PWM Driver:**
```python
success, message = drive.reinitialize()
# Automatically restores previous frequency/amplitude if drive was enabled
```

**Temperature Driver:**
```python
success, message = temp.reinitialize()
# Returns: (bool, str) - success status and message
```

**Benefits:**
- Allows hardware hot-plugging without restarting application
- Can be called from diagnostics/engineer screen
- Automatically detects transition from mock to real hardware
- Preserves drive state when reinitializing PWM driver

### Future Enhancements

**Option 1: Periodic Hardware Check**
Add optional periodic checking (every N seconds) to automatically detect newly connected hardware.

**Option 2: Force Hardware Mode**
Add configuration option to force hardware mode (fail if hardware unavailable).

## Current Usage

**Best Practice:**
- Connect all hardware **before starting** the application
- Check logs for `[MOCK]` warnings to verify hardware detection
- Use `probe()` method (if available) to check hardware status

**For Development:**
- Mock mode works perfectly for UI testing
- No hardware required for development

## Hardware Requirements

### ADC (ADS1115)
- I2C bus (typically `/dev/i2c-1` on Raspberry Pi)
- Address: 0x48 (default, configurable)
- Python packages: `adafruit-circuitpython-ads1x15`

### Drive PWM
- Raspberry Pi GPIO (or compatible)
- `pigpio` daemon running: `sudo pigpiod`
- Python package: `pigpio`

### Temperature (MAX31865)
- SPI bus
- CS pin (configurable, e.g., GPIO 5)
- Python packages: `adafruit-circuitpython-max31865`

## Detection Logic

All drivers follow this pattern:
1. Try to import required libraries
2. Try to connect to hardware
3. If either fails → use mock
4. Log warning message indicating mock mode

The mock implementations now provide realistic behavior for testing.

