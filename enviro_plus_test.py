import time
import numpy as np

# Import sensori Enviro+
try:
    from bme280 import BME280
    from enviroplus.noise import Noise
    from pms5003 import PMS5003
    #from tcs34725 import TCS34725
except ImportError as e:
    print("Import Error:", e)
    print("Assicurati di avere la libreria enviroplus installata")
    exit(1)

# Inizializza sensori
print("Inizializzazione sensori Enviro+...")
bme = None
noise = None
pms = None
tcs = None

# BME280
try:
    bme = BME280()
    print("BME280 OK")
except Exception as e:
    print("BME280 non trovato:", e)

# Microfono
try:
    noise = Noise()
    print("Microfono OK (verifica valori >0)")
except Exception as e:
    print("Microfono non disponibile:", e)

# PMS5003
try:
    pms = PMS5003()
    print("PMS5003 OK")
except Exception as e:
    print("PMS5003 non disponibile:", e)

# TCS34725
try:
    tcs = TCS34725()
    print("TCS34725 OK")
except Exception as e:
    print("TCS34725 non disponibile:", e)

print("\n--- Test sensori ---\n")

try:
    while True:
        # BME280
        if bme:
            try:
                temp = bme.get_temperature()
                hum = bme.get_humidity()
                pres = bme.get_pressure()
                print(f"Temp: {temp:.2f} °C, Umidità: {hum:.2f} %, Pressione: {pres:.2f} hPa")
            except Exception as e:
                print("Errore BME280:", e)

        # Microfono
        if noise:
            try:
                amp = noise.amplitude()
                if amp == 0:
                    print("Microfono: segnale 0 → probabilmente non funziona")
                else:
                    print(f"Microfono amplitude: {amp:.6f}")
            except Exception as e:
                print("Errore microfono:", e)

        # PMS5003
        if pms:
            try:
                data = pms.read()
                print(f"PMS5003: PM1.0={data.pm_ug_per_m3(1):.1f}, PM2.5={data.pm_ug_per_m3(2):.1f}, PM10={data.pm_ug_per_m3(10):.1f}")
            except Exception as e:
                print("Errore PMS5003:", e)

        # TCS34725
        if tcs:
            try:
                r, g, b, c = tcs.get_raw_data()
                print(f"TCS34725: R={r}, G={g}, B={b}, C={c}")
            except Exception as e:
                print("Errore TCS34725:", e)

        print("-" * 40)
        time.sleep(2)

except KeyboardInterrupt:
    print("Test interrotto dall'utente")
