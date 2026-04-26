# Flower Rover Control Center

Bu loyiha laptopni robotning "miya" qatlami sifatida ishlatadi:

- `ESP32` motor va nasoslarni bajaradi.
- `Python server` telefon uchun local web app, kameralar, telemetriya va keyingi avtonomni boshqaradi.
- `USB Serial` notebook va ESP32 orasidagi asosiy aloqa yo'li bo'ladi.
- `YOLOWorld` old/chap/o'ng kamerada gullarni aniqlaydi.
- `Auto spray` yoqilganda har bir kamerada gul markazga tushsa mos spray kanalga pulse yuboradi.
- `Old kamera` endi ikki vazifani bajaradi: yo'lni ko'rsatadi va old spray zonasini trigger qiladi.

## Nega aynan local server?

Bu yerda "server ko'tarish" degani cloud emas. Shu laptopning o'zida local HTTP server ishga tushadi, telefon esa shu Wi-Fi ichida brauzer orqali ulanadi.

## Geometriya Eslatmasi

Robot hozir chel ustidan yuradigan konseptga moslangan. `config.json` ichidagi
`lane_width_cm` nomi eski compatibility uchun qoldirilgan reference o'lchov.
Real yurish xavfsizligi hardware geometriyasi, g'ildirak joylashuvi va amaliy
kalibrovkaga bog'liq.

Aniq avtonom yurish kerak bo'lsa keyingi bosqichda encoder, IMU yoki front vision
feedback qo'shish mumkin.

## Ishga tushirish

1. `config.example.json` ni `config.json` ga ko'chiring.
2. Ichidagi `esp32.serial_port` va kamera indekslarini moslang.
3. ESP32 ga [robot_controller_example.ino](/home/seymonbek/Flowers/esp32/robot_controller_example.ino) ni yozing.
4. Virtual muhitdan:

```bash
.venv/bin/python main.py
```

So'ng telefon brauzerida:

```text
http://LAPTOP_IP:8765
```

## ESP32 USB Serial Rejimi

Default config endi Wi-Fi o'rniga USB Serial ishlatadi:

```json
{
  "esp32": {
    "transport": "serial",
    "serial_port": "auto",
    "baudrate": 115200
  }
}
```

ESP32 portini tekshirish:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

`serial_port: "auto"` bo'lsa server `/dev/serial/by-id/*`, `/dev/ttyACM*` va
`/dev/ttyUSB*` portlardan birini avtomatik tanlaydi. Agar bir nechta qurilma
ulangan bo'lsa, `config.json` ichida portni aniq yozing. Windowsda bu odatda
`COM3`, `COM4` kabi bo'ladi.

Firmware ichida `ENABLE_WIFI_AP = false`, shuning uchun ESP32 Wi-Fi AP ko'tarmaydi
va notebook bilan USB orqali gaplashadi. Agar eski Wi-Fi HTTP rejim kerak bo'lsa,
firmware'da `ENABLE_WIFI_AP = true`, configda esa `transport: "http"` qiling.

## Telefon Home Screen Ilova Rejimi

APK build qilmasdan ham telefon ekranida ilovadek ochish mumkin:

1. Laptopda serverni ishga tushiring.
2. Telefon va laptop bir xil Wi-Fi tarmoqda bo'lsin.
3. Telefon brauzerida `http://LAPTOP_IP:8765` ni oching.
4. Chrome menyusidan `Add to Home screen` yoki `Install app` ni bosing.
5. Keyingi safar `Flower Rover` ikonkasidan oching.

Eslatma: true APK qilish ham mumkin, lekin u Android Studio/Android SDK bilan alohida build qilinadi. Bu loyiha hozir PWA/shortcut rejimiga tayyor.

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
- detect kamera va spray mapping

Build yoki development paytida kamera/ESP32 ulanmagan bo'lsa:

```bash
.venv/bin/python main.py doctor --skip-cameras --skip-esp32
```

## Kamera va Spray Mapping

Hozirgi default konfiguratsiya quyidagicha:

```text
front camera -> flower detection
left camera  -> operator monitoring
right camera -> operator monitoring
front detect -> left + right pump yoki valve
```

Default kamera sozlamasi laptopning ichki kamerasini chetlab, 3 ta tashqi USB
kamerani ishlatadi:

```json
[
  { "name": "front", "source": "external:0", "enabled": true, "detect_flowers": true },
  { "name": "left", "source": "external:1", "enabled": true, "detect_flowers": false },
  { "name": "right", "source": "external:2", "enabled": true, "detect_flowers": false }
]
```

Windowsda `external:0`, `external:1`, `external:2` odatda `1`, `2`, `3`
indekslarga moslanadi, ya'ni `0` bo'ladigan laptop ichki kamerasi ishlatilmaydi.
Kamera joylari almashib qolsa `config.json` ichidagi `external:0/1/2` qiymatlarini
front/left/right orasida almashtiring.

ESP32 tarafida hozir ishlatiladigan default pump pinlari:

```text
left pump  -> GPIO 16
right pump -> GPIO 17
```

`GPIO 23` dagi old/front chiqish firmware ichida saqlangan, lekin hozirgi default config uni ishlatmaydi. Agar keyin alohida front valve qo'shsangiz qayta yoqish mumkin.

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
- `90° chap` va `90° o'ng` avtomatik burilish tugmalari bor.
- Tugma bosib turilsa yuradi, qo'yib yuborilsa stop yuboriladi.
- Eski kechikkan manual commandlar sequence orqali ignor qilinadi.
- Mobil brauzerda long-press `copy/select` menyusi bloklangan.
- 3 kamera stream oynasi mavjud.
- Faqat old kamera flower detection qiladi.
- Auto spray default holatda `left + right` kanalga pulse yuboradi.
- Doctor va unit testlar mavjud.

## Kengaytirish yo'li

- Encoder feedback bilan haqiqiy metr hisoblash
- Yon sensorlar bilan markaz ushlash PID
- Old kameradan chel/row following
- Batareya, nasos bosimi, suv sathi telemetriyasi
