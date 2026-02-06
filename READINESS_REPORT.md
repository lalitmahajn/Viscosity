# Raspberry Pi Deployment Readiness Report

**Status:** ⚠️ **Not Ready** (Requires dependency updates & system setup)

Your project has a solid architectural foundation for Raspberry Pi (clean separation of drivers, mock fallbacks, service files), but it is missing critical dependencies and system-level configuration to strictly "just work" upon deployment.

## 1. Critical Blockers

### A. Missing Hardware Dependencies
The `requirements.txt` file has the actual hardware libraries commented out. If you deploy now, the application will run in **MOCK MODE** (simulating data) instead of reading real sensors.

**Action Required:**
Uncomment or add the following to `requirements.txt` (or create a `requirements-pi.txt`):
```text
RPi.GPIO>=0.7.1
smbus2>=0.4.3
spidev>=3.6
adafruit-circuitpython-ads1x15>=2.0.0
pigpio>=1.78
```

### B. System-Level Dependencies (APT)
The UI uses `tkinter` and audio uses `sounddevice`. These require system packages that `pip` cannot install.

**Action Required:**
Run this on the Pi:
```bash
sudo apt-get update
sudo apt-get install python3-tk python3-pigpio pigpio libportaudio2 -y
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```
*Note: The PWM driver explicitly requires the `pigpiod` daemon running.*

## 2. Configuration Review

### Service File (`deploy/viscologic.service`)
The service file is well-written but assumes:
1.  Username is `pi`.
2.  App location is `/home/pi/viscologic`.
3.  Python is `/usr/bin/python3` (system python).

**Recommendation:**
If you use a virtual environment (recommended), update line 30:
```ini
ExecStart=/home/pi/viscologic/.venv/bin/python -m viscologic.app
```

### UI & Display
The app uses **Tkinter**.
- **Headless:** If the Pi has no screen, you must set `ui_enabled: false` in `config/settings.yaml` or ensure the generic fallback in `app.py` works (it currently prints stats to console).
- **With Screen:** Ensure the Pi automatically logs in and boots to desktop (or uses X11 start) for the window to appear.

## 3. Codebase Strengths (Good News)
- **Mock Fallbacks:** Your drivers (`adc_ads1115.py`, `drive_pwm.py`) are excellent. They automatically detect missing hardware/libraries and switch to simulation mode. This means **the app will not crash** if you deploy it as-is; it just won't measure anything real.
- **Config Manager:** Use of `os.getcwd()` and relative paths means file paths will work correctly on Linux.
- **Service Architecture:** The app allows safe imports, meaning it won't fail if you invoke it before all files are copied (useful during incremental deployment).

## 4. Summary of Next Steps
1.  **Update `requirements.txt`** to include hardware libs.
2.  **Install System Deps** (`python3-tk`, `pigpio`, `libportaudio2`) on the Pi.
3.  **Enable Interfaces** (`sudo raspi-config` -> Interface Options -> Enable I2C, SPI, SSH).
4.  **Deploy Code** to `/home/pi/viscologic`.
5.  **Install Service:**
    ```bash
    sudo cp deploy/viscologic.service /etc/systemd/system/
    sudo systemctl enable --now viscologic
    ```
