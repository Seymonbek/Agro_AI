# Flower Rover Control Center

Bu loyiha laptopni robotning "miya" qatlami sifatida ishlatadi:

- `ESP32` motor va nasoslarni bajaradi.
- `Python server` telefon uchun local web app, kameralar, telemetriya va keyingi avtonomni boshqaradi.
- `YOLOWorld` chap/o'ng kamerada gullarni ko'rishga tayyor turadi.
- `Auto spray` yoqilganda chap/o'ng kamerada gul markazga tushsa mos nasosga pulse yuboradi.
- `Old kamera` faqat yo'l va harakatni ko'rish uchun ishlatiladi.

## Nega aynan local server?

Bu yerda "server ko'tarish" degani cloud emas. Shu laptopning o'zida local HTTP server ishga tushadi, telefon esa shu Wi-Fi ichida brauzer orqali ulanadi.

## Muhim geometriya

- Agatlar orasidagi masofa: `70 sm`
- Siz aytgan robot eni: `65-66 sm`
- Har tomondagi zaxira: taxminan `2-2.5 sm`

Demak oddiy "7 metr oldinga yur" avtonomi juda xavfli. Amaliy tavsiya:

1. Ikkala yon tomonga masofa sensori qo'ying.
2. G'ildirakka encoder qo'ying.
3. IMU qo'ying.
4. Avtonomda harakatni "meter only" emas, "lane centering + encoder distance" qiling.

## Ishga tushirish

1. `config.example.json` ni `config.json` ga ko'chiring.
2. Ichidagi `esp32.base_url` va kamera indekslarini moslang.
3. Auto spray ishlashi uchun ESP32 ga [robot_controller_example.ino](/home/seymonbek/Flowers/esp32/robot_controller_example.ino) dagi `advanced` endpointlarni yozing.
4. Virtual muhitdan:

```bash
.venv/bin/python main.py
```

So'ng telefon brauzerida:

```text
http://LAPTOP_IP:8765
```

## Doctor tekshiruvi

Ishga tushirishdan oldin avtomatik tekshiruv:

```bash
.venv/bin/python main.py doctor
```

Bu quyidagilarni tekshiradi:

- `config.json`
- YOLO model
- web assetlar
- yoqilgan kameralar
- ESP32 javobi
- auto spray rejimi

## Eski kamera demo

Avvalgi dual-camera prototip saqlab qolingan:

```bash
.venv/bin/python main.py vision-demo
```

## Windows `.exe`

Windows kompyuterda:

1. `Python 3.10+` o'rnating.
2. `build_windows.bat` ni ishga tushiring.
3. Script CPU uchun `torch/torchvision`, `clip`, `ultralytics` va `pyinstaller` ni o'rnatadi.
4. `dist/FlowerRoverControl/` ichida tayyor papka chiqadi.
5. Avval `DOCTOR_CHECK.bat` ni oching.
6. Keyin `START_FLOWER_ROVER.bat` yoki `FlowerRoverControl.exe` ni ishga tushiring.

Windows build oqimi:

- `FlowerRoverControl.spec` PyInstaller uchun to'liq paketlash fayli
- `config.example.json` birinchi ishga tushganda `config.json` bo'lib nusxalanadi
- build oxirida `doctor --skip-cameras --skip-esp32` smoke test ishlaydi
- real ishga tushirishdan oldin to'liq `doctor` ni target kompyuterda ishga tushiring
- `.cache/clip/ViT-B-32.pt` mavjud bo'lsa release papkaga qo'shiladi va YOLOWorld uchun offline cache bo'lib xizmat qiladi

## Avtonom segment formati

Web app ichida mana bunaqa JSON kiritiladi:

```json
[
  { "label": "1-qator oldinga", "left": 0.55, "right": 0.55, "meters": 7.0 },
  { "label": "Joyida burilish", "left": -0.45, "right": 0.45, "seconds": 1.1 }
]
```

`meters` bo'lsa server uni `full_speed_mps` kalibrovkasiga qarab sekundga aylantiradi.

## Kengaytirish yo'li

- YOLO aniqlashga qarab avtomatik nasos trigger qo'shish
- Encoder feedback bilan haqiqiy metr hisoblash
- Yon sensorlar bilan markaz ushlash PID
- Old kameradan row following
- Batareya, nasos bosimi, suv sathi telemetriyasi
