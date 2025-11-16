import numpy as np
import sounddevice as sd
from scipy import signal

# Parametri
RATE = 48000   # Hz
BLOCK = 4800   # 0.1 s
REF = 1.0      # riferimento arbitrario

# Filtro A-weighting (coeff. biquad)
def a_weighting(fs):
    f1, f2, f3, f4 = 20.6, 107.7, 737.9, 12194.0
    A1000 = 1.9997
    nums = [(2*np.pi*f4)**2 * (10**(A1000/20)), 0, 0, 0, 0]
    dens = np.polymul([1, 4*np.pi*f4, (2*np.pi*f4)**2],
                      [1, 4*np.pi*f1, (2*np.pi*f1)**2])
    dens = np.polymul(np.polymul(dens, [1, 2*np.pi*f3]),
                      [1, 2*np.pi*f2])
    return signal.bilinear(nums, dens, fs)

b, a = a_weighting(RATE)

def rms_dbA(data):
    # filtro A-weighting
    y = signal.lfilter(b, a, data)
    rms = np.sqrt(np.mean(y**2))
    if rms == 0:
        return -np.inf
    return 20 * np.log10(rms / REF)

# Callback di acquisizione
def callback(indata, frames, time, status):
    if status:
        print(status)
    level = rms_dbA(indata[:,0])
    print(f"dBA stimati: {level:.1f}")

with sd.InputStream(channels=1, samplerate=RATE, blocksize=BLOCK, callback=callback):
    print("Misuratore dBA (premi Ctrl+C per uscire)...")
    while True:
        pass
