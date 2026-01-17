from viscologic.drivers.drive_pwm import DrivePWM

drv = DrivePWM({"gpio_pin": 18})

ok, msg = drv.probe()
print("Probe:", ok, msg)

drv.start(freq_hz=200, amplitude=0.4)
print(drv.get_status())

drv.stop()
print(drv.get_status())
