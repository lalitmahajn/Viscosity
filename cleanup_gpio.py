import lgpio
import time

try:
    # Try to open and close chip 0 to 4 (most common)
    for i in range(5):
        try:
            h = lgpio.gpiochip_open(i)
            lgpio.gpiochip_close(h)
            print(f"Chip {i} closed.")
        except:
            pass
    print("Cleanup attempted.")
except Exception as e:
    print(f"Cleanup error: {e}")
