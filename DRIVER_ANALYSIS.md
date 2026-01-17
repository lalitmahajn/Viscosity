# Driver Modules Analysis

## Overview
This document analyzes the three driver modules in `viscologic/drivers/`:
1. `adc_ads1115.py` - ADC (Analog-to-Digital Converter) driver
2. `drive_pwm.py` - PWM drive output controller
3. `temp_max31865.py` - Temperature sensor driver

---

## 1. ADC Driver (`adc_ads1115.py`)

### ✅ **Implemented Methods:**
- `read_sample_volts()` - ✅ Used by orchestrator
- `read_samples(n, sleep_hint)` - Available but not used
- `probe()` - Diagnostics
- `close()` - Cleanup

### ⚠️ **Missing Methods:**
- `read()` - Orchestrator tries this as fallback (line 785, commented out)
  - **Impact:** Low (hasattr check prevents crash)
  - **Recommendation:** Add alias method for compatibility

### ✅ **Features:**
- ✅ Hardware support: Adafruit CircuitPython ADS1115 library
- ✅ Mock fallback: Works on Windows/dev machines without hardware
- ✅ Configurable: I2C bus, address, gain, data rate, differential channels
- ✅ Error handling: Graceful fallback to mock on hardware failure

### 📝 **Code Quality:**
- Good error handling
- Proper type hints
- Clear documentation
- Mock implementation for development

---

## 2. Drive PWM Driver (`drive_pwm.py`)

### ✅ **Implemented Methods:**
- `set_frequency(freq_hz)` - ✅ Used by orchestrator
- `set_amplitude(amplitude)` - ✅ Used by orchestrator (fallback)
- `start(freq_hz, amplitude, soft_start)` - Available
- `stop()` - ✅ Used by orchestrator
- `get_status()` - Returns DriveStatus dataclass
- `probe()` - Diagnostics

### ❌ **MISSING Methods (CRITICAL):**
- `set_duty(duty)` - ❌ **Orchestrator calls this (lines 285, 837)**
  - **Impact:** HIGH - Orchestrator expects this method
  - **Current:** Falls back to `set_amplitude()` but not ideal
  - **Fix Needed:** Add `set_duty()` method (can alias to `set_amplitude()`)

- `get_duty()` - ❌ **Orchestrator calls this (line 820)**
  - **Impact:** MEDIUM - Used to get current duty cycle
  - **Current:** Falls back to `start_duty` config value
  - **Fix Needed:** Add `get_duty()` method to return current `_amp` value

### ✅ **Features:**
- ✅ Hardware support: pigpio library for Raspberry Pi GPIO
- ✅ Mock fallback: Works on Windows/dev machines
- ✅ Soft start: Ramp-up functionality to prevent sudden drive changes
- ✅ Configurable: GPIO pin, PWM range, default frequency/amplitude

### ⚠️ **Issues:**
1. **Missing `set_duty()` method** - Orchestrator expects this
2. **Missing `get_duty()` method** - Orchestrator expects this
3. **Type hint issue:** Line 61 uses `tuple[bool, str]` (Python 3.9+) instead of `Tuple[bool, str]`

### 📝 **Code Quality:**
- Good structure
- Proper error handling
- Mock implementation available
- Needs missing methods added

---

## 3. Temperature Driver (`temp_max31865.py`)

### ✅ **Implemented Methods:**
- `read_temp_c()` - ✅ Used by orchestrator (primary)
- `read()` - ✅ Used by orchestrator (fallback, line 770)
  - **Note:** Returns mock object with `temperature` property, not direct value
- `probe()` - Diagnostics

### ⚠️ **Potential Issues:**
- `read()` method doesn't exist, but orchestrator checks for it
  - **Current:** Orchestrator checks `hasattr(self.temp, "read")` and calls it
  - **Problem:** `read()` doesn't exist, but mock object has `temperature` property
  - **Impact:** Low (orchestrator has fallback logic)

### ✅ **Features:**
- ✅ Hardware support: Adafruit CircuitPython MAX31865 library
- ✅ Mock fallback: Simulates temperature with gentle oscillation
- ✅ Configurable: CS pin, RTD nominal, reference resistor, wires, filter
- ✅ PT100/PT1000 support

### ⚠️ **Issues:**
1. **Pin resolution:** Only accepts board pin names (e.g., "D5"), not GPIO integers
   - **Impact:** May be confusing for users
   - **Current:** Raises RuntimeError if int provided

### 📝 **Code Quality:**
- Good error handling
- Clear documentation
- Mock implementation available
- Pin resolution could be more flexible

---

## Summary of Issues

### 🔴 **Critical (Must Fix):**
1. **`DrivePWM.set_duty()`** - Missing method called by orchestrator
2. **`DrivePWM.get_duty()`** - Missing method called by orchestrator

### 🟡 **Medium Priority:**
1. **`ADS1115Driver.read()`** - Add alias for compatibility
2. **`MAX31865Driver.read()`** - Consider adding explicit method (currently relies on property)

### 🟢 **Low Priority:**
1. **Type hints:** `drive_pwm.py` line 61 uses Python 3.9+ syntax
2. **Pin resolution:** `temp_max31865.py` could support GPIO integers

---

## Recommendations

### Immediate Actions:
1. ✅ Add `set_duty()` method to `DrivePWM` (alias to `set_amplitude()`)
2. ✅ Add `get_duty()` method to `DrivePWM` (return `self._amp`)
3. ✅ Add `read()` method to `ADS1115Driver` (alias to `read_sample_volts()`)

### Future Enhancements:
1. Add `read()` method to `MAX31865Driver` that returns dict with `temp_c` and `fault` keys
2. Improve GPIO pin resolution in `MAX31865Driver` to support both board names and integers
3. Add unit tests for all driver modules
4. Document expected method signatures in driver base class or interface

---

## Method Call Matrix

| Method | ADC | Drive | Temp | Orchestrator Usage |
|--------|-----|-------|------|-------------------|
| `read_sample_volts()` | ✅ | ❌ | ❌ | ✅ Line 792 |
| `read()` | ⚠️ | ❌ | ⚠️ | ✅ Lines 770, 785 (fallback) |
| `set_frequency()` | ❌ | ✅ | ❌ | ✅ Line 831 |
| `set_duty()` | ❌ | ❌ | ❌ | ✅ Lines 285, 837 |
| `set_amplitude()` | ❌ | ✅ | ❌ | ✅ Line 839 (fallback) |
| `get_duty()` | ❌ | ❌ | ❌ | ✅ Line 820 |
| `stop()` | ❌ | ✅ | ❌ | ✅ Line 291 |
| `read_temp_c()` | ❌ | ❌ | ✅ | ✅ Line 767 |
| `probe()` | ✅ | ✅ | ✅ | Not used (diagnostics only) |

---

## Architecture Notes

### Design Pattern:
- **Duck Typing:** Orchestrator uses `hasattr()` checks for method availability
- **Graceful Degradation:** All drivers have mock fallbacks for development
- **Lazy Initialization:** Hardware connections opened on first use (`_ensure_open()`)
- **Thread Safety:** Not explicitly thread-safe (assumes single-threaded orchestrator loop)

### Mock Strategy:
- All drivers detect hardware unavailability and fall back to mock implementations
- Mocks provide realistic data for UI testing
- No hardware required for development/testing

