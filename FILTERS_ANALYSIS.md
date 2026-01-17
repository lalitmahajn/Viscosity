# Filters.py Analysis and Conclusion

## Executive Summary

**Status:** `filters.py` is **NOT currently being utilized** in the codebase, but it was **intended for the original block-based lock-in amplifier design**. The current streaming implementation doesn't require these filters.

## Investigation Results

### 1. Current Usage
- ✅ **No imports found** - `filters.py` is not imported anywhere in the codebase
- ✅ **No function calls** - None of the filter functions are being called
- ✅ **Available but unused** - The module exists and is functional, but not integrated

### 2. Original Design Intent

**Evidence from `lockin_iq.py` (commented code, lines 112-243):**

The original block-based lock-in amplifier design **WAS intended to use filters**:

```python
# from viscologic.dsp.filters import reject_outliers_mad, rms

# Original method:
#   - Process blocks of samples
#   - Remove outliers using MAD (Median Absolute Deviation)
#   - Calculate RMS for noise estimation
#   - Compute SNR and confidence
```

**Original workflow:**
1. Collect block of ADC samples
2. **Reject outliers** using `reject_outliers_mad()` 
3. Remove DC component
4. Process through lock-in
5. **Calculate RMS** of residual for noise estimation
6. Compute SNR and confidence

### 3. Why Filters Are Not Used Now

**Architecture Change: Block-Based → Streaming**

**Old Design (Block-Based):**
- Processed blocks of samples (e.g., 128 samples)
- Needed outlier rejection (spikes, glitches)
- Needed RMS calculation for noise estimation
- Computed SNR and confidence internally

**Current Design (Streaming):**
- Processes **one sample at a time** (`lockin.update(adc_val)`)
- Built-in **IIR low-pass filter** (handles noise naturally)
- **No outlier rejection needed** (single sample processing)
- **No RMS calculation** (orchestrator uses simple magnitude-based confidence)

### 4. Current Signal Processing Flow

```
ADC.read_sample_volts() 
  → adc_val (single float)
  → lockin.update(adc_val)  [Streaming, IIR filter built-in]
  → magnitude, phase_deg
  → orchestrator._compute_confidence() [Simple heuristic]
```

**No filtering stage** between ADC and lock-in.

### 5. Architecture Plan Reference

From `Final Plan.txt` (lines 143-147):
```
## 7.3 Noise rejection (Digital Lock-in I/Q)
* reference sin/cos at drive frequency
* I/Q multiply + low-pass
* magnitude + phase stable extraction
```

**Plan mentions:**
- ✅ I/Q demodulation (implemented)
- ✅ Low-pass filtering (implemented via IIR in lock-in)
- ❌ No mention of pre-filtering or outlier rejection

**Temperature smoothing mentioned** (line 185):
- "smoothing" for temperature
- But not implemented (temp sensor has its own filtering)

## Where Filters Could Be Useful

### Option 1: Temperature Smoothing ⚠️
**Current:** Temperature read directly from sensor
**Could use:** `EMAFilter` or `moving_average` for smoother display
**Status:** Not implemented, but mentioned in plan

### Option 2: ADC Pre-Filtering ⚠️
**Current:** Raw ADC samples go directly to lock-in
**Could use:** `median_filter` or `reject_outliers_mad` if we buffer samples
**Status:** Not needed for streaming approach

### Option 3: Viscosity Result Smoothing ⚠️
**Current:** Viscosity computed from magnitude directly
**Could use:** `EMAFilter` on final viscosity values
**Status:** Not implemented

### Option 4: Block-Based Processing Mode (Future) 🔮
**If we add:** Optional block-based processing mode
**Would need:** `reject_outliers_mad`, `rms` for noise estimation
**Status:** Not planned

## Conclusion

### ✅ **Filters.py is NOT needed for current implementation**

**Reasons:**
1. **Streaming architecture** - Processes one sample at a time, no outlier rejection needed
2. **Built-in filtering** - Lock-in amplifier has IIR low-pass filter built-in
3. **Simple confidence** - Orchestrator uses magnitude-based heuristic, not SNR-based
4. **No block processing** - Original block-based design was replaced

### 📋 **Recommendations**

#### Option A: Keep filters.py (Recommended)
**Rationale:**
- ✅ Available for future use (temperature smoothing, optional block mode)
- ✅ No harm keeping it (small file, well-tested)
- ✅ Useful for debugging/analysis tools
- ✅ May be needed if we add block-based processing mode

**Action:** Document that it's available but not currently used

#### Option B: Remove filters.py
**Rationale:**
- ❌ Reduces codebase size
- ❌ Removes unused code
- ⚠️ Would need to recreate if block-based mode added later

**Action:** Only if codebase cleanup is priority

#### Option C: Integrate filters for temperature smoothing
**Rationale:**
- ✅ Plan mentions temperature smoothing
- ✅ Would improve temperature display stability
- ✅ Simple integration (add EMAFilter to orchestrator)

**Action:** Optional enhancement

## Final Verdict

**✅ KEEP filters.py** - It's a small, well-written utility module that:
- Was part of the original design
- May be useful for future enhancements
- Doesn't hurt to keep available
- Could be used for temperature smoothing if desired

**❌ NOT CRITICAL** - Current implementation works fine without it due to streaming architecture.

**📝 DOCUMENTATION NEEDED** - Add comment in code explaining why filters.py exists but isn't used.

