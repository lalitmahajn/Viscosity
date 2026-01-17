from viscologic.drivers.adc_ads1115 import ADS1115Driver

adc = ADS1115Driver(cfg={})

ok, msg = adc.probe()
print("Probe:", ok, msg)

# Single sample
v = adc.read_sample_volts()
print("Single sample (V):", v)

# Multiple samples
samples = adc.read_samples(5)
print("Block samples:", samples)
