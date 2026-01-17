# DSP Module Analysis and Fixes

## Overview
The DSP (Digital Signal Processing) module consists of 4 main components:
1. `lockin_iq.py` - Real-time lock-in amplifier
2. `sweep_tracker.py` - Frequency sweep and resonance tracking
3. `health_score.py` - System health scoring
4. `filters.py` - Basic DSP filters (moving average, median, etc.)

## Issues Found and Fixed

### ✅ **Issue 1: Missing Methods in SweepTracker**

**Problem:** The orchestrator was calling methods on `SweepTracker` that didn't exist:
- `submit_point(freq_hz, magnitude)` - line 586
- `is_complete()` - line 587
- `best_freq_hz()` - line 588
- `get_current_freq()` - line 806

**Fix:** Added all missing methods to `SweepTracker`:
- `submit_point()`: Collects sweep data points during frequency sweep
- `is_complete()`: Checks if all frequencies have been swept
- `best_freq_hz()`: Returns the frequency with highest amplitude
- `get_current_freq()`: Returns current frequency being swept (with dwell time handling)
- `reset_sweep()`: Resets sweep state for new sweeps

**Implementation Details:**
- Uses dwell time (`dwell_ms`) to control how long to stay at each frequency
- Maintains list of `SweepPoint` objects during sweep
- Automatically advances through frequency list based on time elapsed
- Tracks sweep completion state

## Module Status

### ✅ **lockin_iq.py** - WORKING
- **Purpose:** Streaming lock-in amplifier for real-time signal processing
- **Features:**
  - I/Q demodulation (mixing with sin/cos references)
  - IIR low-pass filtering
  - Magnitude and phase calculation
  - Phase accumulator for continuous reference generation
- **Status:** ✅ Complete and functional
- **Used by:** Orchestrator calls `lockin.update(adc_val)` every tick

### ✅ **sweep_tracker.py** - FIXED
- **Purpose:** Frequency sweep management and resonance peak finding
- **Features:**
  - Sweep frequency planning
  - Peak selection (by confidence and amplitude)
  - 3-point centroid refinement
  - Phase-locked loop (PLL) frequency tracking
  - **NEW:** Sweep execution with dwell time
- **Status:** ✅ Fixed - all required methods now implemented
- **Used by:** Orchestrator during SWEEPING state

### ✅ **health_score.py** - WORKING
- **Purpose:** Compute system health score (0-100)
- **Features:**
  - Weighted scoring: signal (40%), lock (25%), sensors (20%), safety (15%)
  - Penalties for faults and alarms
  - Returns HealthScore dataclass with breakdown
- **Status:** ✅ Complete and functional
- **Used by:** Orchestrator calls `health.compute(frame)` for health assessment

### ✅ **filters.py** - WORKING
- **Purpose:** Basic DSP filtering utilities
- **Features:**
  - Moving average
  - Median filter
  - Exponential moving average (EMA)
  - Outlier rejection (MAD-based)
  - RMS calculation
- **Status:** ✅ Complete and functional
- **Used by:** Currently not used by orchestrator (available for future use)

## Integration with Orchestrator

### Lock-In Amplifier Usage:
```python
# Every tick:
lock_state = self.lockin.update(adc_val)
mag = lock_state.get("magnitude", 0.0)
ph = lock_state.get("phase_deg", 0.0)
```

### Sweep Tracker Usage:
```python
# During SWEEPING state:
if self.sm.state == SystemState.SWEEPING:
    self.sweep.submit_point(freq_hz=freq_hz, magnitude=mag)
    if self.sweep.is_complete():
        best = self.sweep.best_freq_hz()
        self.lockin.set_ref_freq(float(best))
```

### Health Scorer Usage:
```python
# For health assessment:
result = self.health.compute(frame_input)
health_score = result.score  # 0-100
```

## Notes

1. **Confidence Calculation:** The orchestrator computes confidence itself using a simple heuristic (magnitude-based). The lock-in amplifier doesn't provide SNR/confidence, but this is handled in `_compute_confidence()`.

2. **Sweep Execution:** The sweep now properly handles:
   - Dwell time at each frequency
   - Automatic progression through frequency list
   - Data point collection
   - Best frequency selection

3. **No Breaking Changes:** All fixes are additive - existing functionality preserved.

## Testing Recommendations

1. Test sweep execution with real hardware
2. Verify dwell time behavior
3. Test best frequency selection with various amplitude profiles
4. Verify health scoring with different fault conditions

