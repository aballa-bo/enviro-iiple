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
from subprocess import check_output
from count_people import people_count
from datetime import datetime

# Configurazioni
API_KEY = "YOUR_API"
username = "apikey"
password = API_KEY

# Combina e codifica
user_pass = f"{username}:{password}"
encoded = base64.b64encode(user_pass.encode("utf-8")).decode("utf-8")

OPENPROJECT_URL = "YOUR_API_SERVER/api/v3"

#Frequenza invio dati
TIME_SAMPLE = 300

PROJECT_ID = 5 # PROGETTO IIPLE
TYPE_ID = 8  # WP Type "measurements"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {encoded}", #"Authorization": f"Bearer {API_KEY}"
}

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
             "noise",
             "temp",
             "hum",
             "press",
             "ox",
             "red",
             "nh3",
             "pm1",
             "pm25",
             "pm10"
]

display_units = [
         "Lux",
         "db"
         "°C",
         "%",
         "hPa",
         "ox",
         "red",
         "nh3",
         "ug/m3",
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



def leggi_sensori():
    # Esempio: BME280
    temperature, pressure, humidity = bme280.get_temperature(), bme280.get_pressure(), bme280.get_humidity()


    # Light
    light = ltr559.get_lux()

    # Gas
    gases = gas.read_all()
    oxidising = gases.oxidising / 1000
    reducing = gases.reducing / 1000
    nh3 = gases.nh3 / 1000
    time.sleep(1.0)

    # Noise
    # noise = _noise.get_amplitude_at_frequency_range(20, 8000)
    low, mid, high, amp = noise.get_noise_profile()
    low *= 128
    mid *= 128
    high *= 128
    amp *= 64
    print(f"low:{low}")
    print(f"mid:{mid}")
    print(f"high:{high}")
    print(f"amp:{amp}")
#    noise = (low + mid + high) / 3.0

    # PM
    try:
        pm = pms5003.read()
    except ReadTimeoutError:
        pm = PMS5003()



    return {
        "light": light,
        "noise": noise,
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


# Display Raspberry Pi serial and Wi-Fi status on LCD
def display_everything(values):
    draw.rectangle((0, 0, WIDTH, HEIGHT), (0, 0, 0))
    column_count = 2
    row_count = (len(display_variables) / column_count)
    for i in range(len(display_variables)-4):
        variable = display_variables[i-1]
        data_value = values[variable]
        unit = display_units[i-1]
        x = x_offset + ((WIDTH // column_count) * (i // row_count))
        y = y_offset + ((HEIGHT / row_count) * (i % row_count))
        message = f"{variable[:4]}: {data_value:.1f} {unit}"
        lim = limits[i-1]
        rgb = palette[0]
        for j in range(len(lim)):
            if data_value > lim[j]:
                rgb = palette[j + 1]
        draw.text((x, y), message, font=smallfont, fill=rgb)
    disp.display(img)

def send_to_openproject(data, people, image_to_send=None):
    now = datetime.utcnow().strftime("%Y-%m-%d")  # solo data
    payload = {
        "subject": "Enviro+ contruction site sensor measurement",
        "_links": {
            "project": {"href": f"/api/v3/projects/{PROJECT_ID}"},
            "type": {"href": f"/api/v3/types/{TYPE_ID}"},
            "status": {"href": "/api/v3/statuses/5"
  }
        },

        "customField9": "{:.4f}".format(data["light"]), # lux,
        "customField10": "{:.4f}".format(data["noise"]), # decibel,
        "customField1": "{:.4f}".format(data["temp"]), # decibel,
        "customField2": "{:.4f}". format(data["hum"]),
        "customField14": "{:.4f}".format(data["press"]),
        "customField11": "{:.4f}".format(data["ox"]),
        "customField12": "{:.4f}".format(data["red"]),
        "customField13": "{:.4f}".format(data["nh3"]),
        "customField6": data["pm1"],
        "customField5": data["pm25"],
        "customField8": data["pm10"],
        "customField15": people,
        "customField16": now,
    }

    response = requests.post(
        f"{OPENPROJECT_URL}/work_packages", #f"{OPENPROJECT_URL}/projects/{PROJECT_ID}/work_packages",
        headers=HEADERS,
        json=payload,
        verify=False
    )

    if response.status_code in (200, 201):
        data = response.json()
        workpackage_id = data.get("id")
        print(f"✅ Work package creato con successo! ID: {workpackage_id}")
    else:
        print(f"❌ Errore: status {response.status_code}")
        print(response.text)
        workpackage_id = 0
    return response, workpackage_id


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

def attach_image(workpackage_id):
    with open(IMAGE_ACQUISITION, "rb") as f:
        files = {"file": (IMAGE_ACQUISITION, f, "image/jpeg")}  # cambia tipo se PNG
        attach_response = requests.post(
            f"{OPENPROJECT_URL}/api/v3/work_packages/{workpackage_id}/attachments",
            headers=HEADERS,
            files=files,
            verify=False
        )

    if attach_response.status_code in (200, 201):
        print(f"✅ Allegato caricato con successo su WP {workpackage_id}")
    else:
        print(f"❌ Errore caricamento allegato ({attach_response.status_code})")
        print(attach_response.text)

    return workpackage_id

def main():
    # Main loop to read data, display, and send to Sensor.Community
    global update_time, time_since_update, time_since_image_update, image_update_time
    while True:

        low, mid, high, amp = noise.get_noise_profile()
        low *= 128
        mid *= 128
        high *= 128
        amp *= 64
        print(f"low:{low}")
        print(f"mid:{mid}")
        print(f"high:{high}")
        print(f"amp:{amp}")

        # try:
        values = leggi_sensori()
        print(values)
        print()
        time_since_update = time.time() - update_time
        time_since_image_update = time.time() - image_update_time
        wp_id = 0
        # people, image = people_count(filename=IMAGE_ACQUISITION)
        # print(f"People @ site: {people}")
        # Ogni minuto mando la lettura dei sensori del cantiere
        if time_since_update > TIME_SAMPLE:
            logging.info(values)
            update_time = time.time()
            people, image = people_count(filename=IMAGE_ACQUISITION)
            print(f"People @ site: {people}")
            response, wp_id = send_to_openproject(values, people)
            if response.status_code in (200, 201):
                logging.info("Open Project BIM IIPLE - Response: OK")
            else:
                logging.warning("Open Project BIM IIPLE -Response: Failed")
        # # Ogni mattina mando un'immagine del cantiere
        #if time_since_image_update >  and wp_id > 0: #3600
        #     image_update_time = time.time()
        #     response = attach_image(wp_id)
        #     if response.status_code in (200, 201):
        #         logging.info("Image attached")
        #     else:
        #         logging.warning("Image not attached -Response: Failed")

        display_everything(values)
        # except Exception as e:
        #     logging.warning(f"Main Loop Exception: {e}")


if __name__ == "__main__":
    main()
