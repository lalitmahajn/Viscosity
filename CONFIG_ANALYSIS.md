app:
  name: ViscoLogic
  version: 1.0.0
  retention:
    db_days: 90
    csv_days: 30
security:
  commissioning_required_on_first_run: true
  engineer_password: '1234'
  session_timeout_s: 1800
  commissioning:
    require_first_time_lock: true
    allow_reset_by_engineer: true
hardware:
  i2c_bus: 1
  i2c_bus: 1   # Raspberry Pi typically uses Bus 1
  spi_bus: 0
  gpio:
    pwm_pin: 18
    enable_pin: 23
    fault_pin: 24
    pwm_pin: 18        # PIN 12 (GPIO 18) - Hardware PWM 0
    enable_pin: 23     # Optional Enable Pin
    fault_pin: 24      # Optional Fault Input Pin
drivers:
  adc_type: audio
  drive_type: audio
  # --- CRITICAL CONFIG ---
  # For Deployment: Use 'ads1115' and 'pwm' (or any non-audio string)
  # For Dev/Windows: Use 'audio' (mic/speaker) OR 'mock'.
  # NOTE: The code defaults to hardware drivers if not set to 'audio'. 
  #       If hardware is missing, the drivers AUTOMATICALLY switch to mock mode.
  adc_type: audio      # Options: 'audio' (mic), 'ads1115' (hardware/mock)
  drive_type: audio    # Options: 'audio' (speaker), 'pwm' (hardware/mock)
  audio:
    rate: 44100
    chunk: 1024
    input_device_index: null
    input_device_index: null  # null = default mic
    gain: 5.0
    output_device_index: null
    output_device_index: null # null = default speakers
    output_gain: 0.5
  adc_ads1115:
    enabled: true
    i2c_addr: 72
    gain: 1
    i2c_addr: 72   # 0x48 = 72 decimal (Addr pin -> GND)
    gain: 1        # 1 = +/- 4.096V range
    sample_rate_sps: 860
    channel_diff:
    - 0
    - 1
    - 0  # A0
    - 1  # A1
    vref: 3.3
    scale: 1.0
  temp_max31865:
    enabled: true
    spi_cs: 0
    rtd_nominal: 100.0
    ref_resistor: 430.0
    spi_cs: 0      # Chip Select 0 (CE0)
    rtd_nominal: 100.0  # PT100 = 100.0, PT1000 = 1000.0
    ref_resistor: 430.0 # 430 ohm for PT100, 4300 for PT1000
    wires: 3
    filter_hz: 50
    filter_hz: 50  # Mains frequency filter (50Hz or 60Hz)
    fault_check_interval_s: 2.0
  drive_pwm:
    enabled: true
    pwm_freq_hz: 20000
    pwm_freq_hz: 20000  # Carrier frequency (outside audible range)
    duty_min: 0.02
    duty_max: 0.85
    start_duty: 0.15
    ramp_step: 0.01
    ramp_interval_ms: 50
dsp:
  target_freq_hz: 180.0
  sweep_span_hz: 5.0
  sweep_step_hz: 0.1
  sweep_dwell_ms: 60
  lockin_tau_s: 0.2
  notch_hz: 50
  notch_q: 20
  bandpass:
    enabled: true
    low_hz: 150
    high_hz: 220
    order: 2
health:
  enable: true
  min_confidence_ok: 60.0
  min_confidence_good: 80.0
  max_freq_jump_hz: 1.0
  max_noise_ratio: 0.6
  max_dropouts_per_min: 10
model:
  feature_key: magnitude_clean
  viscosity_min_cp: 0.01
  viscosity_max_cp: 100000.0
  temp_compensation:
    enabled: true
    reference_temp_c: 25.0
    alpha_per_c: 0.02
calibration:
  active_profile: Default
  min_points_required: 3
  recommended_points:
  - name: Air
    cp: 0.0
  - name: Water
    cp: 1.0
  - name: Std Oil
    cp: 100.0
protocols:
  modbus_server:
    enabled: true
    host: 0.0.0.0
    port: 5020
    port: 5020     # Use 502 for production (requires root)
    unit_id: 1
    update_period_ms: 200
  remote_enable: true
  comm_loss_timeout_ms: 2000
  comm_loss_action: safe_stop
plc:
  allow_remote_start: true
  allow_remote_stop: true
  remote_start_edge: true
  remote_stop_edge: true
  local_stop_always_allowed: true
