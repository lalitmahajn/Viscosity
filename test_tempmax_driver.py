from viscologic.drivers.temp_max31865 import MAX31865Driver

drv = MAX31865Driver({})
ok, msg = drv.probe()
print("Probe:", ok, msg)

for _ in range(5):
    print("Temp:", drv.read_temp_c())
