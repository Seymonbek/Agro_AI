# Flower Rover Control Center

Bu loyiha laptopni robotning "miya" qatlami sifatida ishlatadi:

- `ESP32` motor va nasoslarni bajaradi.
- `Python server` telefon uchun local web app, kameralar, telemetriya va keyingi avtonomni boshqaradi.
- `YOLOWorld` old/chap/o'ng kamerada gullarni aniqlaydi.
- `Auto spray` yoqilganda har bir kamerada gul markazga tushsa mos spray kanalga pulse yuboradi.
- `Old kamera` endi ikki vazifani bajaradi: yo'lni ko'rsatadi va old spray zonasini trigger qiladi.

## Nega aynan local server?

Bu yerda "server ko'tarish" degani cloud emas. Shu laptopning o'zida local HTTP server ishga tushadi, telefon esa shu Wi-Fi ichida brauzer orqali ulanadi.

## Muhim geometriya

Robot endi ikkita chel orasidan emas, chelning ustidan yuradigan konseptga moslangan.

`config.json` ichidagi `lane_width_cm` nomi compatibility uchun qoldirilgan, lekin bu loyihada uning ma'nosi:

```text
chel ustida robot xavfsiz bosib yuradigan track kengligi
```

Shu sababli oddiy "7 metr oldinga yur" avtonomi chel ustida ham xavfli. Amaliy tavsiya:

1. Front kamera bilan chel markazini ko'ring.
2. G'ildirakka encoder qo'ying.
3. IMU qo'ying.
4. Avtonomda harakatni "meter only" emas, "chel center tracking + encoder distance" qiling.

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

Faqat web app/pult/dashboardni kamera ulanmagan holda ko'rib chiqmoqchi bo'lsangiz:

```bash
.venv/bin/python main.py --demo-cameras
```

Bu rejimda 3 ta demo kamera oynasi chiqadi va `auto spray` xavfsizlik uchun avtomatik o'chiriladi.

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
- left/front/right spray mapping

Build yoki development paytida kamera/ESP32 ulanmagan bo'lsa:

```bash
.venv/bin/python main.py doctor --skip-cameras --skip-esp32
```

## Kamera va Spray Mapping

Final soft arxitektura 3 ta detection kamera va 3 ta spray kanalga tayyor:

```text
left camera  -> left pump yoki valve
front camera -> front pump yoki valve
right camera -> right pump yoki valve
```

Default kamera indekslari:

```json
[
  { "name": "front", "source": 0, "enabled": true, "detect_flowers": true },
  { "name": "left", "source": 1, "enabled": true, "detect_flowers": true },
  { "name": "right", "source": 2, "enabled": true, "detect_flowers": true }
]
```

Windows kompyuterda kamera tartibi boshqacha chiqsa `config.json` ichidagi `source` qiymatlarini almashtiring. Masalan front kamera aslida `1` bo'lsa, `front.source` ni `1` qiling.

ESP32 tarafida default pump pinlari:

```text
left pump  -> GPIO 16
front pump -> GPIO 23
right pump -> GPIO 17
```

Relay modulingiz active-LOW bo'lsa `PUMP_ACTIVE_HIGH = false` holati to'g'ri. Agar relay gul topilganda teskari ishlasa `PUMP_ACTIVE_HIGH` qiymatini almashtiring.

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
  { "label": "Chel ustida oldinga", "left": 0.55, "right": 0.55, "meters": 7.0 },
  { "label": "Joyida burilish", "left": -0.45, "right": 0.45, "seconds": 1.1 }
]
```

`meters` bo'lsa server uni `full_speed_mps` kalibrovkasiga qarab sekundga aylantiradi.

## Hozirgi Tayyor Holat

- Telefon va kompyuter bitta web dashboard orqali boshqaradi.
- Telefon landscape holatda chap/o'ng va oldinga/orqaga tugmalari bilan ishlaydi.
- Tugma bosib turilsa yuradi, qo'yib yuborilsa stop yuboriladi.
- Eski kechikkan manual commandlar sequence orqali ignor qilinadi.
- 3 kamera stream oynasi mavjud.
- 3 kamera ham flower detection va centered trigger uchun sozlangan.
- Auto spray `left/front/right` kanalga pulse yuboradi.
- Doctor va unit testlar mavjud.

## Kengaytirish yo'li

- Encoder feedback bilan haqiqiy metr hisoblash
- Yon sensorlar bilan markaz ushlash PID
- Old kameradan chel/row following
- Batareya, nasos bosimi, suv sathi telemetriyasi
