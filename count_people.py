import subprocess
from ultralytics import YOLO
import cv2
import sys
import os

def people_count(filename="construction_site.jpg", model_path="yolov8n.pt"):
    """
    Scatta un'immagine, rileva persone con YOLOv8.

    """

    # 1️⃣ Scatta la foto con rpicam-still
    subprocess.run(
        ["rpicam-still", "-o", filename, "-t", "2000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    # 2️⃣ Carica immagine con OpenCV
    img = cv2.imread(filename)

    sys_stdout = sys.stdout
    sys_stderr = sys.stderr

    # 4️⃣ Reindirizza tutto verso /dev/null
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

    try:
        # Carica modello YOLOv8 in modalità silenziosa
        model = YOLO(model_path)
        results = model(img, verbose=False)  # verbose=False riduce i log interni
    finally:
        # Ripristina stdout/stderr
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = sys_stdout
        sys.stderr = sys_stderr

    # 5️⃣ Conta solo persone (classe 0 in COCO)
    num_people = sum(1 for det in results[0].boxes if int(det.cls[0]) == 0)


    # # 6️⃣ Invia immagine e conteggio a OpenProjectBIM
    # headers = {"Authorization": f"Bearer {api_key}"}
    # files = {"file": open(filename, "rb")}
    # data = {"project_id": project_id, "num_people": num_people}
    #
    # response = requests.post(api_url, headers=headers, files=files, data=data)
    # if response.ok:
    #     print("✅ Dati inviati correttamente a OpenProjectBIM")
    # else:
    #     print("❌ Errore nell'invio:", response.status_code, response.text)

    return num_people, img


# if __name__ == "__main__":
#     while True:
#         people, img = people_count()
#         print(f"Numero di persone rilevate {people}")