import colorsys
import os
import sys
import time
import json
import base64
import st7735
import requests
import logging
import time
import re
import numpy as np
import sounddevice as sd

from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFont
from bme280 import BME280
from smbus2 import SMBus
from enviroplus import gas
from enviroplus.noise import Noise
from pms5003 import PMS5003, ReadTimeoutError
from ltr559 import LTR559
from PIL import Image, ImageDraw, ImageFont
from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFont
import subprocess
from subprocess import check_output
from count_people import people_count
from datetime import datetime, time as dt_time, date, timedelta
import os

# Imposta fuso orario
os.environ['TZ'] = 'Europe/Rome'
time.tzset()

# ============================================================
# PARAMETRI SCHEDULAZIONE - MODIFICABILI
# ============================================================
GIORNI_INVIO = [0, 1, 2, 3, 4]  # 0=Lunedì, 1=Martedì, 2=Mercoledì, 3=Giovedì, 4=Venerdì, 5=Sabato, 6=Domenica
ORA_INIZIO = dt_time(8, 0)  # Inizio invii
ORA_FINE = dt_time(17, 0)    # Fine invii
FREQUENZA_INVIO_MINUTI = 5   #5# Invio ogni N minuti
ORA_FOTO_MATTINA = dt_time(8, 5)  # Orario prima foto
ORA_FOTO_SERA = dt_time(12, 55)     # Orario ultima foto
TIMEZONE = 'Europe/Rome'  # Fuso orario
# ============================================================

# Configurazioni
API_KEY = ""
username = "apikey"
password = API_KEY

# Combina e codifica
user_pass = f"{username}:{password}"
encoded = base64.b64encode(user_pass.encode("utf-8")).decode("utf-8")

OPENPROJECT_URL = "https://137.204.62.166/api/v3"

#Frequenza invio dati
TIME_SAMPLE = FREQUENZA_INVIO_MINUTI * 60 

PROJECT_ID = 5 # PROGETTO IIPLE
TYPE_ID = 8  # WP Type "measurements"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {encoded}", #"Authorization": f"Bearer {API_KEY}"
}

# Endpoint di produzione (stessa chiave API del test)
OPENPROJECT_URL_PROD = "https://et4d.dt.edili.com/api/v3"
PROJECT_ID_PROD = 10  # PROGETTO PRODUZIONE
TYPE_ID_PROD = 8      # WP Type "measurements"

# Destinazioni a cui inviare ogni misurazione (test + produzione).
# Gli invii sono indipendenti: se una fallisce, l'altra viene comunque tentata.
DESTINAZIONI = [
    {"nome": "TEST",       "url": OPENPROJECT_URL,      "project_id": PROJECT_ID,      "type_id": TYPE_ID},
    {"nome": "PRODUZIONE", "url": OPENPROJECT_URL_PROD, "project_id": PROJECT_ID_PROD, "type_id": TYPE_ID_PROD},
]
DEST_BY_NOME = {d["nome"]: d for d in DESTINAZIONI}

# Coda su disco per le misure non inviate (assenza di rete): reinvio quando torna online.
# Percorso relativo alla WorkingDirectory del servizio (/home/administrator/iiple).
CODA_FILE = "pending_measurements.jsonl"
CODA_MAX = 5000  # numero massimo di misure conservate su disco

# Configurazione display
# Create LCD instance
disp = st7735.ST7735(
    port=0,
    cs=1,
    dc="GPIO9",
    backlight="GPIO12",
    rotation=270,
    spi_speed_hz=10000000
)

delay = 0.5  # Debounce the proximity tap
mode = 0  # The starting mode
last_page = 0

disp.begin()

WIDTH = disp.width
HEIGHT = disp.height
IMAGE_ACQUISITION = "construction_site.jpg"

# Create a values dict to store the data
display_variables = [
             "light",
             "temp",
             "hum",
             "press",
             "ox",
             "red",
             "nh3",
             "pm1",
             "pm10"
]

display_units = [
         "Lux",
         "°C",
         "%",
         "hPa",
         "ox",
         "red",
         "nh3",
         "ug/m3",
         "ug/m3"
]

# Initialize display

# Set up canvas and font
img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))
draw = ImageDraw.Draw(img)
font_size_small = 10
font_size_large = 20
font = ImageFont.truetype(UserFont, font_size_large)
smallfont = ImageFont.truetype(UserFont, font_size_small)
x_offset = 2
y_offset = 2

message = ""
top_pos = 25

limits = [[-1, -1, 30000, 100000],
          [-1, -1, 0, 100],
          [4, 18, 28, 35],
          [20, 30, 60, 70],
          [250, 650, 1013.25, 1015],
          [-1, -1, 40, 50],
          [-1, -1, 450, 550],
          [-1, -1, 200, 300],
          [-1, -1, 50, 100],
          [-1, -1, 50, 100],
          [-1, -1, 50, 100],
          [-1, -1, 50, 100]]

# RGB palette for values on the combined screen
palette = [(0, 0, 255),           # Dangerously Low
           (0, 255, 255),         # Low
           (0, 255, 0),           # Normal
           (255, 255, 0),         # High
           (255, 0, 0)]           # Dangerously High

logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S")

logging.info("""enviro.py - Reads temperature, pressure, humidity,
PM2.5, and PM10 from Enviro plus and sends data to IIPLE Open Project BIM.

Press Ctrl+C to exit!

""")

bus = SMBus(1)

# Create BME280 instance
bme280 = BME280(i2c_dev=bus)

# Particolato PMS5003
pms5003 = PMS5003()

# Light instance
ltr559 = LTR559()

# Noise
noise = Noise()



# ============================================================
# MICROFONO UMIK-1 (USB) - Misura del livello sonoro in dB SPL
# ============================================================
UMIK_CAL_FILE = "/iiple/umik-calibration/716-7462_90deg.txt"
UMIK_DURATION = 1.0          # secondi di acquisizione per ogni lettura
UMIK_SPL_REFERENCE = 120.0   # dB - riferimento miniDSP per il Sens Factor

def carica_sens_factor(path):
    """Legge il 'Sens Factor' (dB) dall'header del file di calibrazione UMIK-1.

    L'header ha la forma: \"Sens Factor =-1.906dB, SERNO: 7167462\"
    """
    try:
        with open(path, "r") as f:
            prima_riga = f.readline()
        m = re.search(r"Sens Factor\s*=\s*(-?\d+(?:\.\d+)?)", prima_riga)
        if m:
            sf = float(m.group(1))
            logging.info(f"🎤 UMIK-1 Sens Factor = {sf} dB (da {path})")
            return sf
        logging.warning(f"⚠️ 'Sens Factor' non trovato in {path}")
    except Exception as e:
        logging.warning(f"⚠️ Impossibile leggere il file di calibrazione {path}: {e}")
    return 0.0

# Caricato una sola volta all'avvio
UMIK_SENS_FACTOR = carica_sens_factor(UMIK_CAL_FILE)

def trova_umik():
    """Ritorna (indice_dispositivo, samplerate) del microfono UMIK-1, o (None, None)."""
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and "umik" in dev["name"].lower():
                return idx, int(dev["default_samplerate"])
    except Exception as e:
        logging.warning(f"⚠️ Errore nella ricerca dei dispositivi audio: {e}")
    return None, None

def leggi_noise_umik():
    """Cattura un breve campione dal UMIK-1 e ritorna il livello in dB SPL.

    Ritorna None se il microfono non e' disponibile o in caso di errore.
    Calibrazione: SPL = dBFS + (120 - Sens Factor), con dBFS riferito a
    sinusoide a fondo scala = 0 dBFS (convenzione miniDSP/REW).
    """
    device, samplerate = trova_umik()
    if device is None:
        logging.warning("⚠️ UMIK-1 non trovato tra i dispositivi audio USB")
        return None
    try:
        n_campioni = int(samplerate * UMIK_DURATION)
        rec = sd.rec(n_campioni, samplerate=samplerate, channels=1,
                     dtype="float32", device=device)
        sd.wait()
        samples = rec[:, 0]
        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms <= 0:
            return None
        # dBFS riferito a sinusoide a fondo scala = 0 dBFS
        dbfs = 20.0 * np.log10(rms * np.sqrt(2.0))
        spl = dbfs + (UMIK_SPL_REFERENCE - UMIK_SENS_FACTOR)
        logging.debug(f"🎤 UMIK-1: rms={rms:.5f} dBFS={dbfs:.1f} SPL={spl:.1f} dB")
        return float(spl)  # float Python nativo, non numpy.float64
    except Exception as e:
        logging.warning(f"⚠️ Errore durante la lettura del UMIK-1: {e}")
        return None


def leggi_sensori():
    # Esempio: BME280
    temperature, pressure, humidity = bme280.get_temperature()-3.5, bme280.get_pressure(), bme280.get_humidity()+20.0


    # Light
    light = ltr559.get_lux()

    # Gas
    gases = gas.read_all()
    oxidising = gases.oxidising / 1000
    reducing = gases.reducing / 1000
    nh3 = gases.nh3 / 1000
    time.sleep(1.0)

    # Noise - livello sonoro in dB SPL dal microfono UMIK-1 (USB)
    spl = leggi_noise_umik()

    # PM
    try:
        pm = pms5003.read()
    except ReadTimeoutError:
        pm = PMS5003()



    return {
        "light": light,
        "noise": spl,
        "temp": temperature,
        "hum": humidity,
        "press": pressure,
        "ox": oxidising,
        "red": reducing,
        "nh3": nh3,
        "pm1": pm.pm_ug_per_m3(1.0),
        "pm25": pm.pm_ug_per_m3(2.5),
        "pm10": pm.pm_ug_per_m3(10)
    }


def media_misure(buffer):
    """Calcola la media campo per campo di una lista di letture sensori.

    buffer: lista di dict restituiti da leggi_sensori().
    Ritorna un singolo dict con la media di ogni chiave numerica.
    """
    if not buffer:
        return None

    chiavi = buffer[0].keys()
    medie = {}
    for chiave in chiavi:
        valori = [m[chiave] for m in buffer if m.get(chiave) is not None]
        medie[chiave] = sum(valori) / len(valori) if valori else 0
    return medie


# Get Raspberry Pi serial number to use as ID
def get_serial_number():
    with open("/proc/cpuinfo", "r") as f:
        for line in f:
            if line.startswith("Serial"):
                return line.split(":")[1].strip()


# Check for Wi-Fi connection
def check_wifi():
    if check_output(["hostname", "-I"]):
        return True
    else:
        return False

# ============================================================
# STATO RETE - connettivita' e tipo di interfaccia
# ============================================================
RETE_CACHE_TTL = 30  # secondi tra un controllo di connettivita' e il successivo
_rete_cache = {"ts": 0.0, "online": False, "tipo": None}

def rileva_interfaccia():
    """Interfaccia della default route: 'ETH', 'WIFI', il nome grezzo, o None."""
    try:
        out = check_output(["ip", "route", "show", "default"]).decode()
        for line in out.splitlines():
            parti = line.split()
            if "dev" in parti:
                dev = parti[parti.index("dev") + 1]
                if dev.startswith(("eth", "en")):
                    return "ETH"
                if dev.startswith(("wlan", "wl")):
                    return "WIFI"
                return dev
    except Exception as e:
        logging.debug(f"rileva_interfaccia: {e}")
    return None

def internet_disponibile():
    """True se 8.8.8.8 risponde al ping entro 2 secondi."""
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception as e:
        logging.debug(f"internet_disponibile: {e}")
        return False

def stato_rete():
    """Ritorna (online: bool, tipo: 'ETH'|'WIFI'|None).

    Il risultato e' messo in cache per RETE_CACHE_TTL secondi per non lanciare
    un ping ad ogni iterazione del loop.
    """
    ora = time.time()
    if ora - _rete_cache["ts"] < RETE_CACHE_TTL:
        return _rete_cache["online"], _rete_cache["tipo"]
    tipo = rileva_interfaccia()
    online = internet_disponibile() if tipo else False
    _rete_cache.update(ts=ora, online=online, tipo=tipo)
    return online, tipo


# Mostra stato invii, connettivita' e valori sensori sul LCD
def display_everything(values, stato_invii, online=False, tipo_rete=None):
    draw.rectangle((0, 0, WIDTH, HEIGHT), (0, 0, 0))

    # --- Riga di stato in alto ---
    # Indicatori invio: grigio = nessun invio, verde = OK, rosso = fallito
    def colore_stato(ok):
        if ok is None:
            return (120, 120, 120)
        return (0, 255, 0) if ok else (255, 0, 0)

    barra_h = 13
    draw.text((x_offset, 1), "TEST", font=smallfont, fill=colore_stato(stato_invii.get("TEST")))
    draw.text((x_offset + 42, 1), "PROD", font=smallfont, fill=colore_stato(stato_invii.get("PRODUZIONE")))

    # Stato rete: verde = online, arancio = connesso ma senza internet, rosso = offline
    if tipo_rete and online:
        rete_txt, rete_col = tipo_rete, (0, 255, 0)
    elif tipo_rete and not online:
        rete_txt, rete_col = tipo_rete + "?", (255, 165, 0)
    else:
        rete_txt, rete_col = "OFF", (255, 0, 0)
    draw.text((x_offset + 88, 1), rete_txt, font=smallfont, fill=rete_col)
    draw.line((0, barra_h, WIDTH, barra_h), fill=(60, 60, 60))

    # --- Griglia valori sensori (sotto la riga di stato) ---
    column_count = 2
    row_count = (len(display_variables) / column_count)
    area_h = HEIGHT - barra_h
    for i in range(len(display_variables)):
        variable = display_variables[i]
        data_value = values[variable]
        unit = display_units[i]
        x = x_offset + ((WIDTH // column_count) * (i // row_count))
        y = barra_h + 1 + ((area_h / row_count) * (i % row_count))
        message = f"{variable[:4]}: {data_value:.1f} {unit}"
        lim = limits[i]
        rgb = palette[0]
        for j in range(len(lim)):
            if data_value > lim[j]:
                rgb = palette[j + 1]
        draw.text((x, y), message, font=smallfont, fill=rgb)

    disp.display(img)

def send_to_openproject(data, people, dest, data_misura=None):
    # Usa la data originale della misura se fornita (reinvii dalla coda),
    # altrimenti la data odierna.
    now = data_misura or datetime.utcnow().strftime("%Y-%m-%d")
    payload = {
        "subject": "Enviro+ construction site sensor measurement",
        "_links": {
            "project": {"href": f"/api/v3/projects/{dest['project_id']}"},
            "type": {"href": f"/api/v3/types/{dest['type_id']}"}
        },
        "percentageDone": 100,  # Imposta come completato al 100%

        "customField9": "{:.4f}".format(data["light"]), # lux,
        "customField10": "{:.4f}".format(data["noise"]), # decibel,
        "customField1": "{:.4f}".format(data["temp"]), # decibel,
        "customField2": "{:.4f}". format(data["hum"]),
        "customField14": "{:.4f}".format(data["press"]),
        "customField11": "{:.4f}".format(data["ox"]),
        "customField12": "{:.4f}".format(data["red"]),
        "customField13": "{:.4f}".format(data["nh3"]),
        "customField6": int(round(data["pm1"])),
        "customField5": int(round(data["pm25"])),
        "customField8": int(round(data["pm10"])),
        "customField15": people,
        "customField16": now,
    }

    try:
        # Crea il work package (senza specificare status, usa quello di default)
        response = requests.post(
            f"{dest['url']}/work_packages",
            headers=HEADERS,
            json=payload,
            verify=False,
            timeout=30
        )

        if response.status_code in (200, 201):
            data = response.json()
            workpackage_id = data.get("id")
            print(f"✅ [{dest['nome']}] Work package creato! ID: {workpackage_id}")
        else:
            print(f"❌ Errore: status {response.status_code}")
            print(response.text)
            workpackage_id = 0
        return response, workpackage_id

    except requests.exceptions.Timeout:
        logging.error("⏱️ Timeout: il server non ha risposto entro 30 secondi")
        return None, 0
    except requests.exceptions.ConnectionError as e:
        logging.error(f"🔌 Errore di connessione: {e}")
        return None, 0
    except Exception as e:
        logging.error(f"❌ Errore imprevisto durante l'invio: {e}")
        return None, 0


# ============================================================
# CODA SU DISCO - reinvio delle misure quando la rete torna disponibile
# ============================================================
def accoda_misura(valori, people, data_misura, destinazioni_nomi):
    """Salva su file una misura non inviata, con le destinazioni ancora da servire."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "data_misura": data_misura,
        "people": people,
        "valori": valori,
        "pending": list(destinazioni_nomi),
    }
    try:
        with open(CODA_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logging.info(f"\U0001F4BE Misura salvata in coda (destinazioni pendenti: {entry['pending']})")
    except Exception as e:
        logging.error(f"❌ Impossibile salvare la misura in coda: {e}")
    _limita_coda()

def _carica_coda():
    if not os.path.exists(CODA_FILE):
        return []
    entries = []
    try:
        with open(CODA_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        logging.error(f"❌ Errore lettura coda: {e}")
    return entries

def _salva_coda(entries):
    try:
        with open(CODA_FILE, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    except Exception as ex:
        logging.error(f"❌ Errore salvataggio coda: {ex}")

def _limita_coda():
    entries = _carica_coda()
    if len(entries) > CODA_MAX:
        _salva_coda(entries[-CODA_MAX:])
        logging.warning(f"⚠️ Coda troncata alle ultime {CODA_MAX} misure")

def flush_coda():
    """Reinvia le misure in coda alle destinazioni ancora pendenti.

    Da chiamare solo quando c'e' connettivita'. Si interrompe al primo errore
    di rete (per non bloccare il loop con tanti timeout) e riprende al giro dopo.
    """
    entries = _carica_coda()
    if not entries:
        return
    logging.info(f"\U0001F4E4 Flush coda: {len(entries)} misure da reinviare...")
    rimaste = []
    interrotto = False
    for entry in entries:
        if interrotto:
            rimaste.append(entry)
            continue
        ancora_pending = []
        for nome in entry.get("pending", []):
            if interrotto:
                ancora_pending.append(nome)
                continue
            dest = DEST_BY_NOME.get(nome)
            if dest is None:
                continue  # destinazione non piu' configurata: scarta
            response, wp_id = send_to_openproject(
                entry["valori"], entry["people"], dest, entry.get("data_misura"))
            if response is None:
                ancora_pending.append(nome)
                interrotto = True
                logging.warning(f"\U0001F50C [coda->{nome}] rete assente: flush interrotto")
            elif response.status_code in (200, 201):
                logging.info(f"✅ [coda->{nome}] reinviata (WP {wp_id}, misura {entry.get('ts')})")
            elif response.status_code >= 500:
                ancora_pending.append(nome)
                logging.warning(f"⚠️ [coda->{nome}] server non disponibile ({response.status_code}): resta in coda")
            else:
                logging.error(f"❌ [coda->{nome}] rifiutata ({response.status_code}): scartata")
        if ancora_pending:
            entry["pending"] = ancora_pending
            rimaste.append(entry)
    _salva_coda(rimaste)
    if rimaste:
        logging.info(f"\U0001F4BE Restano {len(rimaste)} misure in coda")
    else:
        logging.info("✅ Coda svuotata")


# Raspberry Pi ID to send to Sensor.Community
id = "raspi-" + get_serial_number()

# Width and height to calculate text position
WIDTH = disp.width
HEIGHT = disp.height

# Text settings
font_size = 16
font = ImageFont.truetype(UserFont, font_size)

# Log Raspberry Pi serial and Wi-Fi status
logging.info(f"Raspberry Pi serial: {get_serial_number()}")
wifi_status = "connected" if check_wifi() else "disconnected"
logging.info(f"Wi-Fi: {wifi_status}\n")

time_since_update = 0
update_time = time.time()
time_since_image_update = 0
image_update_time = time.time()

def sincronizza_orologio():
    """Sincronizza l'orologio di sistema tramite timedatectl"""
    try:
        logging.info("Sincronizzazione orologio in corso...")
        os.system("sudo timedatectl set-ntp true")
        time.sleep(2)
        logging.info("✅ Orologio sincronizzato")
        return True
    except Exception as e:
        logging.warning(f"⚠️ Errore sincronizzazione orologio: {e}")
        return False

def scatta_foto():
    """Scatta una foto dalla camera Sony IPX5000"""
    try:
        logging.info("Scatto foto in corso...")
        # Comando per scattare foto (da adattare al tuo setup specifico)
        #os.system(f"libcamera-still -o {IMAGE_ACQUISITION} --timeout 2000")
        subprocess.run(
            ["rpicam-still", "-o", IMAGE_ACQUISITION, "-t", "2000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        #
        logging.info(f"✅ Foto salvata: {IMAGE_ACQUISITION}")
        return True
    except Exception as e:
        logging.warning(f"⚠️ Errore scatto foto: {e}")
        return False

def in_orario_invio():
    """Verifica se siamo in un giorno e orario valido per l'invio"""
    now = datetime.now()
    giorno_settimana = now.weekday()
    ora_corrente = now.time()

    # Verifica giorno
    if giorno_settimana not in GIORNI_INVIO:
        logging.debug(f"❌ Invio non consentito - Giorno: {giorno_settimana} non in {GIORNI_INVIO}")
        return False

    # Verifica orario - gestisce anche il caso dell'attraversamento della mezzanotte
    if ORA_INIZIO < ORA_FINE:
        # Caso normale: es. 9:30 - 13:00
        in_range = ORA_INIZIO <= ora_corrente < ORA_FINE
    else:
        # Caso attraversamento mezzanotte: es. 22:00 - 01:00
        in_range = ora_corrente >= ORA_INIZIO or ora_corrente < ORA_FINE

    if not in_range:
        logging.debug(f"❌ Invio non consentito - Ora: {ora_corrente} fuori range {ORA_INIZIO}-{ORA_FINE}")
        return False

    logging.debug(f"✅ Invio consentito - Giorno: {giorno_settimana}, Ora: {ora_corrente}")
    return True

def attach_image(workpackage_id, dest):
    try:
        with open(IMAGE_ACQUISITION, "rb") as f:
            file_content = f.read()
            files = {
                "metadata": (None, '{"fileName": "' + IMAGE_ACQUISITION + '"}', "application/json"),
                "file": (IMAGE_ACQUISITION, file_content, "image/jpeg")
            }
            attach_response = requests.post(
                f"{dest['url']}/work_packages/{workpackage_id}/attachments",
                headers={"Authorization": f"Basic {encoded}"},
                files=files,
                verify=False,
                timeout=60  # Timeout più lungo per upload foto
            )

        if attach_response.status_code in (200, 201):
            print(f"✅ Allegato caricato con successo su WP {workpackage_id}")
        else:
            print(f"❌ Errore caricamento allegato ({attach_response.status_code})")
            print(attach_response.text)

        return workpackage_id

    except requests.exceptions.Timeout:
        logging.error("⏱️ Timeout upload foto: il server non ha risposto entro 60 secondi")
        return 0
    except requests.exceptions.ConnectionError as e:
        logging.error(f"🔌 Errore di connessione durante upload foto: {e}")
        return 0
    except FileNotFoundError:
        logging.error(f"📁 File foto non trovato: {IMAGE_ACQUISITION}")
        return 0
    except Exception as e:
        logging.error(f"❌ Errore imprevisto durante upload foto: {e}")
        return 0

def main():
    # Main loop to read data, display, and send to Sensor.Community
    global update_time, time_since_update, time_since_image_update, image_update_time
    sincronizza_orologio()
    now = datetime.now()
    oggi = now.date()
    ora_corrente = now.time()
    giorno_settimana = now.weekday()
    print(f"giorno settimana: {giorno_settimana}")
    print(f"oggi: {oggi}")
    print(f"Ora corrente: {ora_corrente}")

    # Variabili per tracciare foto scattate
    foto_mattina_scattata = False
    foto_sera_scattata = False
    ultima_data_controllo = None
    orologio_sincronizzato_oggi = False
    stato_invii = {d["nome"]: None for d in DESTINAZIONI}  # Stato invio per destinazione (display)
    buffer_misure = []  # Letture accumulate in RAM tra un invio e il successivo

    while True:
        now = datetime.now()
        oggi = now.date()
        ora_corrente = now.time()
        giorno_settimana = now.weekday()

        # Reset flag giornalieri se è un nuovo giorno
        if ultima_data_controllo != oggi:
            foto_mattina_scattata = False
            foto_sera_scattata = False
            orologio_sincronizzato_oggi = False
            stato_invii = {d["nome"]: None for d in DESTINAZIONI}
            buffer_misure = []
            ultima_data_controllo = oggi

        # Sincronizza orologio al mattino (una volta al giorno)
        if giorno_settimana in GIORNI_INVIO and not orologio_sincronizzato_oggi:
            if ora_corrente >= dt_time(9, 0) and ora_corrente < dt_time(9, 10):
                sincronizza_orologio()
                orologio_sincronizzato_oggi = True

        # Scatta foto mattutina
        if giorno_settimana in GIORNI_INVIO and not foto_mattina_scattata:
            mattina_fine = (datetime.combine(date.today(), ORA_FOTO_MATTINA) + timedelta(minutes=5)).time()
            if ora_corrente >= ORA_FOTO_MATTINA and ora_corrente < mattina_fine:
                scatta_foto()
                foto_mattina_scattata = True

        # Scatta foto serale e sincronizza orologio
        if giorno_settimana in GIORNI_INVIO and not foto_sera_scattata:
            sera_fine = (datetime.combine(date.today(), ORA_FOTO_SERA) + timedelta(minutes=5)).time()
            if ora_corrente >= ORA_FOTO_SERA and ora_corrente < sera_fine:
                sincronizza_orologio()
                scatta_foto()
                foto_sera_scattata = True

        try:
            values = leggi_sensori()
            print(values)
            print()
            time_since_update = time.time() - update_time
            wp_id = 0
            # Accumula solo in orario di acquisizione: fuori orario/di notte
            # il buffer resta vuoto e non consuma RAM
            if in_orario_invio():
                buffer_misure.append(values)

            # Invio dati solo se siamo in orario e giorno valido
            if time_since_update > TIME_SAMPLE:
                logging.debug(f"⏱️  Time check OK: {time_since_update:.1f}s > {TIME_SAMPLE}s")

            if in_orario_invio() and time_since_update > TIME_SAMPLE:
                logging.info("=" * 60)
                logging.info(f"⏱️  TENTATIVO INVIO - {now.strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info(values)
                update_time = time.time()
                # Media delle letture accumulate dall'ultimo invio
                valori_invio = media_misure(buffer_misure) or values
                logging.info(f"📊 Media su {len(buffer_misure)} letture accumulate")
                buffer_misure = []
                people, image = people_count(filename=IMAGE_ACQUISITION)
                print(f"👥 People @ site: {people}")

                # Determina se allegare foto (prima e ultima del giorno)
                allega_foto = False
                mattina_datetime = datetime.combine(date.today(), ORA_FOTO_MATTINA) + timedelta(minutes=10)
                finestra_mattina = mattina_datetime.time()
                sera_datetime = datetime.combine(date.today(), ORA_FOTO_SERA) + timedelta(minutes=10)
                finestra_sera = sera_datetime.time()
                if (foto_mattina_scattata and ora_corrente < finestra_mattina) or \
                   (foto_sera_scattata and ora_corrente >= ORA_FOTO_SERA and ora_corrente < finestra_sera):
                    allega_foto = True
                    logging.info(f"📷 Foto da allegare: {IMAGE_ACQUISITION}")

                # Prima smaltisci l'eventuale backlog su disco (se c'e' rete)
                online_ora, _ = stato_rete()
                if online_ora:
                    flush_coda()

                logging.info(f"📤 Invio dati a OpenProject BIM ({len(DESTINAZIONI)} destinazioni)...")
                destinazioni_fallite = []
                for dest in DESTINAZIONI:
                    response, wp_id = send_to_openproject(valori_invio, people, dest)

                    if response is None:
                        logging.warning(f"❌ [{dest['nome']}] Invio FALLITO (timeout o errore connessione)")
                        stato_invii[dest['nome']] = False
                        destinazioni_fallite.append(dest['nome'])
                    elif response.status_code in (200, 201):
                        logging.info(f"✅ [{dest['nome']}] Invio OK (WP ID: {wp_id})")
                        stato_invii[dest['nome']] = True

                        # Allega foto se necessario
                        if allega_foto and wp_id > 0:
                            logging.info(f"📎 [{dest['nome']}] Allego foto in corso...")
                            result = attach_image(wp_id, dest)
                            if result > 0:
                                logging.info(f"✅ [{dest['nome']}] Foto allegata al work package")
                            else:
                                logging.warning(f"⚠️ [{dest['nome']}] Allego foto fallito")
                    elif response.status_code >= 500:
                        logging.warning(f"❌ [{dest['nome']}] Invio FALLITO (Status: {response.status_code}) - server")
                        stato_invii[dest['nome']] = False
                        destinazioni_fallite.append(dest['nome'])
                    else:
                        logging.warning(f"❌ [{dest['nome']}] Invio RIFIUTATO (Status: {response.status_code})")
                        logging.warning(f"   Errore: {response.text[:200]}")
                        stato_invii[dest['nome']] = False

                # Salva su disco le misure non inviate (rete/server) per il reinvio
                if destinazioni_fallite:
                    accoda_misura(valori_invio, people,
                                  datetime.utcnow().strftime("%Y-%m-%d"), destinazioni_fallite)

                logging.info("=" * 60)

            online, tipo_rete = stato_rete()
            display_everything(values, stato_invii, online, tipo_rete)
        except Exception as e:
            logging.warning(f"Main Loop Exception: {e}")


if __name__ == "__main__":
    main()
