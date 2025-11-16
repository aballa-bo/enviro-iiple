import sounddevice as sd
import numpy as np

# Parametri
DEVICE = 1       # card 1 = adau7002
SAMPLERATE = 48000
BLOCKSIZE = 480  # 0.01s circa
CHANNELS = 1

print("Avvio test microfono Enviro+ (premi Ctrl+C per uscire)")

try:
    while True:
        # Registrazione breve
        audio = sd.rec(BLOCKSIZE, samplerate=SAMPLERATE, channels=CHANNELS,
                       device=DEVICE, dtype='float32')
        sd.wait()

        # Mostra primi campioni
        print("Primi campioni grezzi:", np.round(audio[:10,0], 6))
        
        # RMS del blocco
        rms = np.sqrt(np.mean(audio**2))
        print(f"RMS blocco: {rms:.6f}\n")

except KeyboardInterrupt:
    print("Test interrotto dall'utente")
except Exception as e:
    print("Errore:", e)
