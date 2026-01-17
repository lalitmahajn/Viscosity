# Storage Package Analysis

## Overview
The `viscologic/storage/` package provides data persistence and logging capabilities. It consists of:
1. `sqlite_store.py` - SQLite database for persistent storage
2. `csv_logger.py` - CSV file logging for measurement data
3. `retention.py` - File retention management for cleanup

## Files

### 1. `sqlite_store.py` (506 lines)
**Purpose:** SQLite database persistence layer for device state, settings, calibration data, and events.

**Database Schema:**
- **meta** - Key-value metadata storage
- **device_state** - Single-row table for commissioning status and last selections
- **settings** - Key-value settings storage (JSON-encoded)
- **calibration_profiles** - Calibration profile definitions
- **calibration_points** - Calibration measurement points (legacy)
- **events** - Event/audit log

**Key Features:**
- Thread-safe operations (RLock)
- WAL mode for better concurrency
- Foreign key constraints enabled
- Autocommit mode (isolation_level=None)
- Connection pooling (new connection per operation)

**Key Methods:**
- `init_db()` - Initialize database schema
- `get_device_state()` / `is_commissioned()` / `mark_commissioned()` - Commissioning management
- `set_setting()` / `get_setting()` - Key-value settings
- `create_profile()` / `list_profiles()` / `delete_profile()` - Profile management
- `add_calibration_point()` / `list_calibration_points()` - Calibration data
- `log_event()` / `list_events()` - Event logging
- `exec()` / `query_one()` / `query_all()` - Generic SQL helpers

**Thread Safety:** ✅ All operations use `_lock` (RLock)

### 2. `csv_logger.py` (177 lines)
**Purpose:** Thread-safe CSV logging with daily file rotation.

**Features:**
- Daily file rotation (`viscologic_YYYY-MM-DD.csv`)
- Thread-safe writes (RLock)
- Automatic date change detection
- Configurable flush interval
- Start/stop control
- Extra fields stored as JSON

**Default Fields:**
```
timestamp_ms, iso_time, viscosity_cp, temp_c, freq_hz,
health_pct, status_word, alarm_word, extra_json
```

**Key Methods:**
- `start()` - Enable logging and open today's file
- `stop()` - Disable logging and close file
- `log_frame(frame)` - Log a measurement frame
- `is_enabled()` - Check if logging is active

**Thread Safety:** ✅ All operations use `_lock` (RLock)

### 3. `retention.py` (100 lines)
**Purpose:** File retention management for cleanup of old files.

**Features:**
- Non-recursive by default (safe)
- Optional recursive cleanup
- Dry-run mode for testing
- Extension filtering
- Detailed reporting

**Key Methods:**
- `cleanup_folder(folder_path, retention_days, allowed_ext)` - Clean up old files
- Returns `RetentionReport` with statistics

**Thread Safety:** ✅ No shared state, safe for concurrent use

## Issues Found

### ❌ **Issue 1: Missing Database Initialization in Orchestrator**
**Problem:** `Orchestrator.__init__()` creates `SqliteStore` but never calls `init_db()`
**Location:** `viscologic/core/orchestrator.py:102`
**Impact:** Database tables may not exist if orchestrator is initialized before other components
**Status:** ⚠️ **PARTIALLY MITIGATED** - `app.py` and `main_window.py` call `init_db()`, but orchestrator should also call it for robustness

### ❌ **Issue 2: CSV Logger Never Started**
**Problem:** `Orchestrator` creates `CsvLogger` but never calls `start()`
**Location:** `viscologic/core/orchestrator.py:114-117`
**Impact:** CSV logging is disabled by default, no data written
**Status:** 🔴 **CRITICAL** - CSV logging will not work

### ❌ **Issue 3: CSV Logger Never Stopped**
**Problem:** `Orchestrator.stop()` never calls `csv.stop()`
**Location:** `viscologic/core/orchestrator.py:276-299`
**Impact:** File handles may not be properly closed on shutdown
**Status:** ⚠️ **MINOR** - Python will close files on exit, but not graceful

### ❌ **Issue 4: Wrong Method Names in `_log()`**
**Problem:** `Orchestrator._log()` tries to call:
- `csv.log()` or `csv.write_row()` - but method is `log_frame()`
- `sqlite.insert_measurement()` or `sqlite.log_measurement()` - but these methods don't exist
**Location:** `viscologic/core/orchestrator.py:1008-1024`
**Impact:** Logging silently fails (caught by try/except)
**Status:** 🔴 **CRITICAL** - No data is being logged

### ❌ **Issue 5: Frame Format Mismatch**
**Problem:** `Orchestrator._log()` creates frame with `ts` but `CsvLogger.log_frame()` expects `timestamp_ms`
**Location:** `viscologic/core/orchestrator.py:993-1006`
**Impact:** CSV logger may not get correct timestamp
**Status:** ⚠️ **MINOR** - CSV logger has fallback to `now_ms()`

### ❌ **Issue 6: Wrong Retention Method**
**Problem:** `Orchestrator._maybe_run_retention()` calls `retention.run()` but method is `cleanup_folder()`
**Location:** `viscologic/core/orchestrator.py:1032`
**Impact:** Retention cleanup never runs
**Status:** ⚠️ **MINOR** - Old files accumulate

### ❌ **Issue 7: Missing SQLite Measurement Logging**
**Problem:** `SqliteStore` has no method to log measurement data
**Location:** `viscologic/storage/sqlite_store.py`
**Impact:** No measurement history in database
**Status:** ⚠️ **FEATURE GAP** - May be intentional (only events logged)

## Integration Points

### Orchestrator Usage:
```python
# Initialization (in __init__)
self.sqlite = SqliteStore(db_path, logger=self.logger)
# ❌ Missing: self.sqlite.init_db()

self.csv = CsvLogger(csv_dir=csv_path, logger=self.logger)
# ❌ Missing: self.csv.start()

# Logging (in _log)
# ❌ Wrong: self.csv.log(row) or self.csv.write_row(row)
# ✅ Should be: self.csv.log_frame(frame)

# ❌ Wrong: self.sqlite.insert_measurement(row)
# ✅ Should be: self.sqlite.log_event("measurement", row)

# Shutdown (in stop)
# ❌ Missing: self.csv.stop()
```

### CalibrationStore Usage:
```python
# Uses SqliteStore generic methods
self.db.exec(sql, params)
self.db.query_one(sql, params)
self.db.query_all(sql, params)
self.db.last_row_id()
```

## Recommendations

### 🔧 **Fix 1: Initialize Database in Orchestrator**
```python
# In Orchestrator.__init__()
self.sqlite = SqliteStore(db_path, logger=self.logger)
self.sqlite.init_db()  # Add this
```

### 🔧 **Fix 2: Start CSV Logger**
```python
# In Orchestrator.start()
if bool(self._cfg_get("storage.csv_logger.enabled", True)):
    if hasattr(self.csv, "start"):
        self.csv.start()
```

### 🔧 **Fix 3: Stop CSV Logger**
```python
# In Orchestrator.stop()
try:
    if hasattr(self.csv, "stop"):
        self.csv.stop()
except Exception:
    pass
```

### 🔧 **Fix 4: Fix Logging Method Calls**
```python
# In Orchestrator._log()
# Convert row to frame format
frame = {
    "timestamp_ms": int(ts * 1000),
    "viscosity_cp": viscosity_cp,
    "temp_c": temp_c,
    "freq_hz": freq_hz,
    "health_pct": int(confidence),
    "status_word": 0,  # TODO: compute from state
    "alarm_word": 0,   # TODO: compute from alarms
    "mode": mode,
    "state": str(self.sm.state.name),
    "duty": duty,
    "magnitude": mag,
    "phase_deg": ph,
}

# CSV logging
try:
    if bool(self._cfg_get("storage.csv_logger.enabled", True)):
        if hasattr(self.csv, "log_frame"):
            self.csv.log_frame(frame)
except Exception:
    pass

# SQLite event logging (optional)
try:
    if bool(self._cfg_get("storage.sqlite.enabled", True)):
        if hasattr(self.sqlite, "log_event"):
            self.sqlite.log_event("measurement", frame)
except Exception:
    pass
```

### 🔧 **Fix 5: Fix Retention Cleanup**
```python
# In Orchestrator._maybe_run_retention()
try:
    # CSV cleanup
    csv_dir = str(self._cfg_get("storage.csv_logger.folder", "logs"))
    if csv_dir:
        report = self.retention.cleanup_folder(
            csv_dir,
            self._ret_csv_days,
            allowed_ext=[".csv"]
        )
        if report.deleted_files > 0:
            self.logger.info("Retention: deleted %d CSV files", report.deleted_files)
except Exception:
    pass
```

## Current Status

### ✅ **sqlite_store.py** - WORKING
- All methods implemented correctly
- Thread-safe
- Proper error handling
- Used by CalibrationStore, CommissioningManager, EngineerAuth

### ⚠️ **csv_logger.py** - NOT INITIALIZED
- Implementation is correct
- But never started in orchestrator
- Methods called incorrectly

### ⚠️ **retention.py** - NOT USED
- Implementation is correct
- But method called incorrectly
- Never actually runs cleanup

## Testing Recommendations

1. Test database initialization on first run
2. Test CSV logging with daily rotation
3. Test retention cleanup with old files
4. Test thread safety under concurrent access
5. Test graceful shutdown (file closure)
6. Test error handling (disk full, permissions)

## Architecture Notes

- **Separation of Concerns:** Storage modules are well-separated
- **Thread Safety:** All modules use proper locking
- **Error Handling:** Operations are wrapped in try/except (best-effort)
- **Initialization:** Some initialization happens in multiple places (app.py, main_window.py, orchestrator)
- **Logging Strategy:** CSV for time-series, SQLite for events/state

## Summary

The storage package is **well-designed** but has **integration issues** in the orchestrator:
- Database initialization is handled elsewhere (OK)
- CSV logger is never started (CRITICAL)
- Logging methods are called incorrectly (CRITICAL)
- Retention cleanup never runs (MINOR)

All issues are in the **orchestrator integration**, not in the storage modules themselves.

