# Flower Rover Final Soft Tizim Rejasi

## 1. Yangilangan Konsept

Loyiha konsepti yangilandi. Endi robot ikki agat orasidan yuradigan oddiy platforma emas, balki `chel ustidan yuradigan aqlli agro robot` sifatida ko'riladi.

Yangi talablar:

- robot chel ustidan harakatlanadi
- kompyuter robotning asosiy miyasi bo'ladi
- telefon va kompyuterdan boshqarish bo'ladi
- 3 ta kamera ishlatiladi
- 3 ta kamera ham gulni aniqlaydi
- gul aniqlansa va markazga tushsa suv sepiladi
- kompyuter ekranida kameralar, holatlar, ogohlantirishlar va diagnostika ko'rinadi
- tizim keyinchalik avtonom yurishga kengayadi

Asosiy formula:

```text
Laptop = miya
ESP32 = bajaruvchi
Telefon = pult
Kompyuter ekrani = dashboard
3 kamera = ko'rish + gul aniqlash
Nasos/valve tizimi = sepish
```

## 2. Qurilmalar Rollari

### 2.1. Laptop

Laptop quyidagi vazifalarni bajaradi:

- local server ko'taradi
- telefon va kompyuter uchun web app beradi
- 3 kamera oqimini oladi
- YOLO orqali gul aniqlaydi
- markazga tushgan gulni hisoblaydi
- spray qarorini qabul qiladi
- ESP32 ga motor va nasos buyruqlarini yuboradi
- dashboardda barcha holatlarni ko'rsatadi
- log va diagnostika yuritadi
- keyinchalik avtonom yurishni boshqaradi

### 2.2. ESP32

ESP32 oddiy va ishonchli bajaruvchi bo'lishi kerak.

ESP32 vazifalari:

- chap va o'ng motor guruhini boshqarish
- tank drive usulida yurish
- nasos yoki solenoid valve'larni boshqarish
- laptopdan kelgan HTTP/API buyruqlarni bajarish
- failsafe orqali aloqa uzilsa motorni to'xtatish
- emergency stop buyruqlarini darhol bajarish

ESP32 ichida murakkab AI bo'lmasligi kerak. AI va qarorlar laptopda qoladi.

### 2.3. Telefon

Telefon operator pulti bo'ladi.

Telefon vazifalari:

- landscape holatda boshqaruv panelini ko'rsatish
- oldinga/orqaga/chapga/o'ngga tugmalarini berish
- speed slider berish
- auto spray toggle berish
- emergency stop berish
- 3 kamera kichik preview ko'rsatish

### 2.4. Kompyuter Ekrani

Kompyuter ekrani katta operator dashboard bo'ladi.

Kompyuter dashboard vazifalari:

- 3 kamera katta ko'rinishi
- detection box va markaz nuqtasi
- robot harakat holati
- ESP32 online/offline
- kamera online/offline
- spray holati
- warninglar
- loglar
- keyinchalik autonomy holati

## 3. Kamera Arxitekturasi

Endi 3 ta kamera ham aktiv detection qiladi.

### 3.1. Kamera Rollari

| Kamera | Joylashuv | Vazifa |
|---|---|---|
| Front camera | Old tomonda | chel yo'lini ko'rish, olddagi gulni aniqlash, front spray trigger |
| Left camera | Chap tomonda | chapdagi gullarni aniqlash, left spray trigger |
| Right camera | O'ng tomonda | o'ngdagi gullarni aniqlash, right spray trigger |

### 3.2. Kamera Oqimi

Har bir kamera uchun quyidagilar bo'lishi kerak:

- online/offline status
- FPS
- detection count
- flower bounding box
- flower center point
- center line
- centered state
- last detection offset

### 3.3. Front Kamera Ikki Vazifali Bo'ladi

Front kamera:

- chel ustida yurish yo'nalishini ko'rsatadi
- olddagi gulni aniqlaydi
- front spray trigger beradi

Bu sababli front kamera detection va navigation uchun alohida ahamiyatga ega.

## 4. Spray Arxitekturasi

3 ta kamera ham gul topganda sepishi kerak bo'lsa, hardware tomonda 3 ta spray kanali kerak bo'ladi.

### 4.1. Tavsiya Qilingan Final Mapping

```text
left camera  -> left spray
front camera -> front spray
right camera -> right spray
```

### 4.2. Hardware Variantlar

#### Variant A: 3 ta alohida nasos

Eng sodda mantiq:

- left pump
- front pump
- right pump

Afzallik:

- har bir kamera o'z nasosiga ega
- kod mantiqi oddiy
- nosozlikni topish oson

Kamchilik:

- quvvat sarfi ko'proq
- sim va relay ko'proq

#### Variant B: 1 ta kuchli nasos + 3 ta solenoid valve

Professionalroq variant:

- bitta umumiy suv nasosi
- left valve
- front valve
- right valve

Afzallik:

- suv bosimi yaxshiroq boshqariladi
- sanoatga yaqinroq yechim
- kanallarni alohida ochish mumkin

Kamchilik:

- valve kerak
- ulanish murakkabroq

#### Variant C: 2 ta nasos bilan qolish

Bu variant tavsiya qilinmaydi, chunki 3 ta kamera sepishi kerak bo'lsa, front zona alohida boshqarilmay qoladi.

Agar vaqt yetmasa vaqtinchalik yechim:

- front camera centered bo'lsa left va right pump birga ishlaydi

Lekin bu ideal emas.

### 4.3. Spray Trigger Shartlari

Spray faqat quyidagi shartlar bajarilganda bo'lishi kerak:

- auto spray yoqilgan
- kamera online
- YOLO flower topdi
- flower center markaz chizig'iga yaqin
- cooldown tugagan
- pump/valve hozir ishlamayapti
- emergency stop aktiv emas

### 4.4. Spray Pulse

Har bir spray quyidagicha bo'lishi kerak:

```text
pump/valve ON
350 ms kutish
pump/valve OFF
cooldown boshlash
dashboard update
```

Pulse va cooldown qiymatlari config orqali o'zgaradigan bo'lishi kerak.

## 5. Chel Ustidan Yurish Strategiyasi

Robot endi chel ustidan yuradi. Bu ikki agat orasidan yurishdan farq qiladi.

### 5.1. Chel Ustida Yurishdagi Risklar

- robot cheldan sirpanib tushishi mumkin
- chel markazi yo'qolishi mumkin
- kamera burchagi noto'g'ri bo'lsa yo'lni yaxshi ko'rmaydi
- chel balandligi notekis bo'lishi mumkin
- robot eni va g'ildirak joylashuvi chelga mos bo'lishi kerak

### 5.2. Minimal Soft Yondashuv

Birinchi bosqichda:

- operator manual boshqaradi
- front kamera chelni ko'rsatadi
- dashboardda front camera katta bo'ladi
- auto spray yordamchi sifatida ishlaydi

### 5.3. Semi-Autonomous Yondashuv

Keyingi bosqichda:

- front kameradan chel markazi aniqlanadi
- robot chel markazida ushlashga harakat qiladi
- operator faqat start/stop qiladi
- gullarni left/front/right kamera aniqlaydi

### 5.4. Full Autonomous Yondashuv

Ideal holatda kerak bo'ladigan sensorlar:

- encoder
- IMU
- yon masofa sensorlari
- front vision row/chel tracking

To'liq autonomy faqat kamera bilan qilinsa risk yuqori. Sensor feedback qo'shilsa ishonchlilik oshadi.

## 6. Web App Rejalari

Tizimda ikki xil layout bo'lishi kerak.

### 6.1. Telefon Layout

Telefon landscape holatda:

```text
Chap panel:    Chapga / O'ngga
Markaz:        3 kamera preview
O'ng panel:    Oldinga / Orqaga
Past panel:    Speed / Auto spray / Stop
```

Talablar:

- bosib tursa yuradi
- qo'yib yuborsa to'xtaydi
- kechikkan eski command robotni qayta yurgizmaydi
- emergency stop har doim ishlaydi
- UI ortiqcha murakkab bo'lmasin

### 6.2. Kompyuter Layout

Kompyuter dashboard:

```text
Yuqori qism:     status badges
Markaz:          3 kamera katta ko'rinish
Chap panel:      manual control
O'ng panel:      diagnostics
Past panel:      logs / warnings
```

Kompyuter layout hakamlar uchun ham chiroyli ko'rinishi kerak.

## 7. Dashboardda Ko'rsatiladigan Holatlar

### 7.1. ESP32 Status

- online/offline
- IP
- firmware mode
- last command
- last OK time
- last error

### 7.2. Motor Status

- current mode
- left motor value
- right motor value
- speed limit
- moving/stopped
- failsafe status

### 7.3. Camera Status

Har bir kamera uchun:

- online/offline
- FPS
- detection count
- last detection confidence
- offset px
- centered yes/no

### 7.4. Spray Status

Har bir spray kanali uchun:

- left spray on/off
- front spray on/off
- right spray on/off
- last spray side
- last spray time
- trigger count
- cooldown status

### 7.5. Safety Status

- emergency stop
- stale command protection
- Wi-Fi status
- camera error
- ESP timeout
- autonomy warning

## 8. API Dizayni

ESP32 oddiy API berishi kerak.

### 8.1. Motor API

```text
/api/drive?left=0.5&right=0.5&speed=120
/api/stop
/api/speed?value=120
```

### 8.2. Spray API

Final 3 kanal uchun:

```text
/api/pump?side=left&state=on
/api/pump?side=front&state=on
/api/pump?side=right&state=on
```

Yoki valve ishlatilsa:

```text
/api/spray?zone=left&state=on
/api/spray?zone=front&state=on
/api/spray?zone=right&state=on
```

### 8.3. Status API

```text
/api/status
```

Qaytadigan ma'lumot:

- ok
- ip
- uptime
- speedLimit
- pump/valve states
- failsafe status

## 9. Safety Dizayni

Safety softning eng muhim qismi.

### 9.1. Command Safety

- har bir command sequence number bilan boradi
- eski command kechiksa ignore qilinadi
- tugma qo'yib yuborilganda stop ustun bo'ladi
- browser blur bo'lsa stop yuboriladi
- server ESP32 bilan aloqa yo'qotsa warning beradi

### 9.2. ESP32 Failsafe

ESP32 quyidagilarni bajarishi kerak:

- 1-2 sekund command kelmasa motor stop
- emergency stop kelsa motor stop
- API xato bo'lsa xavfsiz holatda qolish
- boot paytida pump OFF
- boot paytida motor OFF

### 9.3. Spray Safety

- boot paytida hamma pump/valve OFF
- spray pulse tugagach OFF
- cooldown bo'lmasa qayta spray qilinmaydi
- emergency stop bo'lsa spray ham OFF
- active low/high relay config aniq bo'lishi kerak

## 10. Avtonom Rivojlanish Bosqichlari

### Bosqich 1: Manual + Smart Spray

Maqsad:

- operator boshqaradi
- 3 kamera gulni aniqlaydi
- centered bo'lsa spray bo'ladi
- dashboard hamma narsani ko'rsatadi

Bu musobaqa uchun eng ishonchli bosqich.

### Bosqich 2: Assisted Driving

Maqsad:

- operator oldinga bosadi
- tizim chel markazidan og'ishni ko'rsatadi
- soft operatorga warning beradi
- optional correction tavsiya qiladi

### Bosqich 3: Semi-Autonomous Chel Following

Maqsad:

- front vision chel markazini aniqlaydi
- robot o'zi sekin markazda yuradi
- operator stop qilishga tayyor turadi
- left/front/right detection spray qiladi

### Bosqich 4: Full Autonomous

Maqsad:

- encoder bilan masofa
- IMU bilan yo'nalish
- vision bilan chel center
- mission planner
- qaytish va burilish segmentlari

## 11. Bosqichma-Bosqich Ish Reja

### 11.1. 1-Bosqich: Talablarni Freeze Qilish

Aniqlanadi:

- nechta pump bor
- nechta valve bor
- front spray alohida bormi
- kamera joylashuvi qayerda
- chel ustida robot balansi qanday
- telefon va laptop Wi-Fi modeli qanday

Chiqish natijasi:

- final hardware mapping
- final camera mapping
- final spray mapping

### 11.2. 2-Bosqich: ESP32 Executor

ESP32 quyidagilarni qila olishi kerak:

- motor drive
- stop
- speed
- left/front/right spray
- status
- failsafe

Chiqish natijasi:

- browser orqali har bir endpoint testdan o'tadi
- pump/valve polarity to'g'ri
- motor smooth start ishlaydi

### 11.3. 3-Bosqich: Laptop Server

Laptop server quyidagilarni bajaradi:

- web app serve
- camera stream
- YOLO detection
- command forwarding
- state store
- logs
- diagnostics

Chiqish natijasi:

- telefon va kompyuter bir xil serverga ulanadi
- state endpoint to'g'ri ma'lumot beradi

### 11.4. 4-Bosqich: 3 Kamera Detection

Har bir kamera tekshiriladi:

- front camera flower detect
- left camera flower detect
- right camera flower detect
- centered detection
- false positive holatlar

Chiqish natijasi:

- 3 kamerada bounding box chiqadi
- markazga tushganda centered bo'ladi

### 11.5. 5-Bosqich: 3 Kanal Spray

Spray test:

- left camera -> left spray
- front camera -> front spray
- right camera -> right spray

Chiqish natijasi:

- har bir kamera o'z zonasini boshqaradi
- noto'g'ri zone trigger bo'lmaydi

### 11.6. 6-Bosqich: Dashboard

Dashboard professional holatga keltiriladi:

- status badges
- camera cards
- detection meta
- pump states
- logs
- warnings
- manual controls

Chiqish natijasi:

- hakamga ko'rsatishga tayyor dashboard

### 11.7. 7-Bosqich: Safety Test

Testlar:

- Wi-Fi uzish
- kamera uzish
- ESP32 reset
- tugmani bosib qo'yib yuborish
- eski command delay
- emergency stop
- pump polarity

Chiqish natijasi:

- robot xavfsiz to'xtaydi
- warninglar chiqadi

### 11.8. 8-Bosqich: Demo Tayyorlash

Demo flow:

1. dashboard ochiladi
2. 3 kamera ko'rsatiladi
3. telefon orqali harakat ko'rsatiladi
4. kompyuterdan control ko'rsatiladi
5. left flower detection
6. front flower detection
7. right flower detection
8. spray trigger
9. emergency stop
10. chel ustidan yurish ko'rsatiladi

## 12. Test Checklist

### 12.1. Kamera Test

- front camera online
- left camera online
- right camera online
- front flower detect
- left flower detect
- right flower detect
- center line to'g'ri
- offset hisoblanadi

### 12.2. Spray Test

- left spray ON/OFF
- front spray ON/OFF
- right spray ON/OFF
- auto spray left
- auto spray front
- auto spray right
- cooldown ishlaydi
- false trigger yo'q

### 12.3. Movement Test

- oldinga
- orqaga
- chapga
- o'ngga
- soft start
- speed slider
- button hold
- button release stop
- emergency stop

### 12.4. Network Test

- laptop ESP32 Wi-Fi ga ulangan
- telefon shu Wi-Fi ga ulangan
- telefon web app ochadi
- kompyuter web app ochadi
- ESP32 status OK
- latency qabul qilinadigan darajada

### 12.5. Safety Test

- server yopilsa robot stop
- telefon sahifadan chiqsa robot stop
- Wi-Fi uzilsa robot stop
- kamera uzilsa app yiqilmaydi
- YOLO topmasa spray bo'lmaydi

## 13. Musobaqa Oldi Checklist

### 13.1. Soft

- final code backup qilingan
- config backup qilingan
- Windows/Ubuntu ishga tushirish yo'li tayyor
- web app telefon va kompyuterda ochiladi
- dashboard professional ko'rinadi
- logs ishlaydi

### 13.2. Hardware

- ESP32 firmware final
- motor driver mahkam
- pump/valve wiring mahkam
- GND common
- alohida quvvat stabil
- USB kameralar mahkam
- suv tizimi oqmaydi

### 13.3. Demo

- operator kimligi aniq
- telefon kimda bo'lishi aniq
- laptop kim boshqarishi aniq
- hakamga aytiladigan gaplar tayyor
- emergency stop mashq qilingan

## 14. Hakamga Tushuntirish Uchun Qisqa Matn

Ushbu robotning soft qismi laptop asosida ishlaydi. Laptop robotning miyasi sifatida 3 ta kamera oqimini qayta ishlaydi, YOLO yordamida gullarni aniqlaydi va gul markazga tushganda mos spray kanalini ishga tushiradi. ESP32 motor va nasos/valve'larni bajaruvchi sifatida boshqaradi. Operator robotni telefon yoki kompyuter orqali boshqarishi mumkin. Kompyuter dashboardida kameralar, detection holati, ESP32 aloqasi, spray status va safety warninglar ko'rinib turadi. Tizim chel ustidan yurishga moslangan va keyinchalik sensorlar yordamida avtonom yurishga kengaytiriladi.

## 15. Yakuniy Professional Xulosa

Final tizim quyidagicha bo'lishi kerak:

- chel ustidan yuradigan robot
- telefon va kompyuterdan boshqaruv
- 3 kamera orqali flower detection
- 3 zona bo'yicha smart spray
- real-time dashboard
- safety-first control
- kengayadigan autonomy arxitekturasi

Eng muhim prioritet:

```text
Stability > Safety > Dashboard clarity > Smart spray > Autonomy
```

Avval ishlaydigan va xavfsiz tizim tayyorlanadi. Keyin autonomy kuchaytiriladi.

