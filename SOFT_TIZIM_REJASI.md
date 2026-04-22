# Flower Rover Soft Tizim Rejasi

## 1. Hujjat Maqsadi

Ushbu hujjat robot loyihasining soft qismini professional, tushunarli va musobaqaga tayyor holatda boshqarish uchun yozildi. Maqsad:

- tizim arxitekturasini aniq belgilash
- har bir qurilmaning vazifasini ajratish
- operator interfeysini standartlashtirish
- xavfsizlik va nosozlik holatlariga tayyor turish
- musobaqa oldi yakuniy tekshiruvlarni bir joyga jamlash

Bu hujjat soft jamoa, hardware jamoa va operator uchun umumiy ishchi yo'riqnoma hisoblanadi.

## 2. Loyiha Maqsadi

Loyiha vazifasi:

- robotni telefon va kompyuterdan boshqarish
- old kamera orqali yo'l, harakat va olddagi gullarni ko'rish
- chap va o'ng kamera orqali yon tomondagi gullarni aniqlash
- gul markazga tushganda mos nasosni ishga tushirish
- robotning barcha muhim holatlarini kompyuter ekranida ko'rsatish
- keyinchalik basic autonomous yurish rejimini qo'shish

Asosiy prinsip:

- `Laptop = miya`
- `ESP32 = bajaruvchi`
- `Telefon = pult`

## 3. Tizim Arxitekturasi

### 3.1. Yuqori Darajadagi Arxitektura

```text
Telefon / Kompyuter brauzeri
            |
            v
     Local Web Server (Laptop)
            |
   -----------------------------
   |            |             |
   v            v             v
3 ta Kamera   YOLO        Dashboard / Logs
            |
            v
      Qaror qabul qilish
            |
            v
         ESP32 API
            |
   ---------------------
   |                   |
   v                   v
 Motor Driver       Relay / Nasos
```

### 3.2. Qurilmalar Roli

#### Laptop

Laptop quyidagi vazifalarni bajaradi:

- local web server ishga tushiradi
- 3 ta kameradan video oqimini oladi
- YOLO orqali gul aniqlashni bajaradi
- operator dashboardni ko'rsatadi
- auto spray mantiqini boshqaradi
- autonomy logikasini hisoblaydi
- ESP32 bilan USB Serial orqali gaplashadi
#### ESP32

ESP32 quyidagi vazifalarni bajaradi:

- motorlarni boshqaradi
- chap, old va o'ng spray kanallarini yoqadi yoki o'chiradi
- laptopdan USB Serial orqali kelgan buyruqlarni qabul qiladi
- failsafe bajaradi
- oddiy, tez va ishonchli executor sifatida ishlaydi

#### Telefon

Telefon quyidagi vazifalarni bajaradi:

- operator pulti bo'ladi
- manual control tugmalarini ko'rsatadi
- kameralarni ko'rsatadi
- auto spray holatini ko'rsatadi
- emergency stop tugmasini beradi

## 4. Funktsional Talablar

### 4.1. Manual Control

Tizim quyidagilarni bajarishi shart:

- oldinga yurish
- orqaga yurish
- chapga burilish
- o'ngga burilish
- bosib turganda yurish
- qo'yib yuborganda to'xtash
- speed slider orqali tezlikni o'zgartirish
- emergency stop

### 4.2. Vision

Tizim quyidagilarni bajarishi shart:

- front kamera oqimini ko'rsatish
- left kamera oqimini ko'rsatish
- right kamera oqimini ko'rsatish
- front, left va right kamerada flower detection ishlatish
- markaz chizig'ini ko'rsatish
- flower bounding box chizish
- flower center nuqtasini ko'rsatish
- centered bo'lsa spray ready holatini aniqlash

### 4.3. Spray Logic

Spray logikasi quyidagicha bo'lishi kerak:

- `left camera -> left pump`
- `front camera -> front pump`
- `right camera -> right pump`
- centered detection bo'lsa spray pulse yuborish
- false triggerni kamaytirish uchun cooldown ishlatish
- bir vaqtning o'zida noto'g'ri takror trigger bo'lmasligi

### 4.4. Diagnostics

Kompyuter ekranida quyidagilar aniq ko'rinib turishi kerak:

- ESP32 online yoki offline
- front kamera online yoki offline
- left kamera online yoki offline
- right kamera online yoki offline
- current movement state
- current speed
- auto spray on yoki off
- last spray time
- last spray side
- last detected flower offset
- warnings

### 4.5. Autonomy

Autonomy minimal darajada quyidagilarni qo'llashi kerak:

- oldindan berilgan segmentlar bo'yicha yurish
- meter yoki second asosida harakat
- burilish segmenti
- stop segmenti
- keyinchalik sensorlarga moslab kengaytirish

## 5. Operator Interfeysi

### 5.1. Telefon Interfeysi

Telefon uchun interfeys landscape holatda quyidagicha bo'lishi kerak:

- chap tomonda `Chapga` va `O'ngga`
- o'ng tomonda `Oldinga` va `Orqaga`
- o'rtada 3 ta kichik kamera
- pastda tezlik slider
- auto spray toggle
- emergency stop

Operator maqsadi:

- bir qo'l bilan boshqarish
- minimal chalkashlik
- tez reaksiyali control

### 5.2. Kompyuter Interfeysi

Kompyuter ekranida dashboard quyidagicha bo'lishi kerak:

- 3 ta kamera kattaroq ko'rinadi
- control panel
- diagnostics panel
- warnings panel
- log yoki oxirgi eventlar maydoni

Kompyuter maqsadi:

- monitoring
- debugging
- taqdimot
- operatorga vaziyatni to'liq ko'rsatish

## 6. Dashboardda Ko'rsatilishi Shart Bo'lgan Ma'lumotlar

### 6.1. Asosiy Holat

- mode: manual yoki autonomous
- speed limit
- active command
- auto spray state

### 6.2. Kamera Holati

- front kamera online/offline
- left kamera online/offline
- right kamera online/offline
- fps
- detections soni
- last detection offset

### 6.3. ESP32 Holati

- online/offline
- base URL
- firmware mode
- last error
- last successful contact time

### 6.4. Spray Holati

- left pump/valve on/off
- front pump/valve on/off
- right pump/valve on/off
- last spray time
- last spray camera
- trigger count

### 6.5. Ogohlantirishlar

Tizim quyidagi warninglarni chiqara olishi kerak:

- ESP32 offline
- kamera offline
- YOLO detect qilmayapti
- tarmoq kechikishi yuqori
- autonomy risk
- hardware yoki autonomy risk ogohlantirishi

## 7. Data Flow

### 7.1. Manual Control Data Flow

```text
Operator tugmani bosadi
-> Web app command yaratadi
-> Laptop server qabul qiladi
-> Server state yangilanadi
-> ESP32 ga command yuboriladi
-> ESP32 motorni boshqaradi
-> Dashboard updated status ko'rsatadi
```

### 7.2. Spray Data Flow

```text
Left/Front/Right kamera frame beradi
-> YOLO flower detection
-> markaz bilan solishtirish
-> centered bo'lsa camera_to_pump mapping
-> ESP32 pump endpoint
-> pump pulse
-> spray state update
-> dashboard log
```

## 8. Safety Talablar

Soft qism uchun eng muhim xavfsizlik talablar:

- tugma qo'yib yuborilganda robot to'xtashi kerak
- stale command qayta yurishga olib kelmasligi kerak
- ESP32 javob bermasa operatorga ko'rinishi kerak
- Wi-Fi uzilsa xavfli harakat davom etmasligi kerak
- auto spray faqat centered detectionda ishlashi kerak
- kamera uzilsa dastur qulamasligi kerak
- emergency stop har doim ustun bo'lishi kerak

## 9. Failure Cases va Kutilgan Javob

| Holat | Sabab | Tizim Javobi |
|---|---|---|
| ESP32 offline | Wi-Fi yoki power muammo | warning chiqarish, operatorni xabardor qilish |
| Left/right kamera offline | USB yoki driver muammo | shu kamera disable holatga o'tadi, tizim qolgan qism bilan yashaydi |
| YOLO detect bermadi | yorug'lik yoki model muammo | false trigger qilinmaydi, faqat detection yo'q deb ko'rsatiladi |
| Tarmoq kechikdi | Wi-Fi lag | stale command ignore qilinadi, stop ustun bo'ladi |
| Nasos polarity teskari | relay active low | config yoki firmware orqali to'g'rilanadi |
| Operator sahifani tark etdi | browser blur | active buttons clear + stop |
| Autonomy xato segment berdi | noto'g'ri input | validation va warning |

## 10. Avtonom Rivojlanish Strategiyasi

### 10.1. Hozirgi Bosqich

Tavsiya etilgan prioritet:

- manual control 100% stabil
- kamera va spray 100% stabil
- diagnostics 100% tushunarli

### 10.2. Keyingi Bosqich

Basic autonomy:

- segment based mission
- seconds va meters
- oldindan belgilangan burilishlar

### 10.3. Ideal Bosqich

To'liq stabil autonomy uchun quyidagilar kerak:

- yon sensorlar
- encoder
- IMU
- chel usti tracking
- feedback control

Faqat `qancha metr yurish` asosidagi autonomy feedbacksiz taxminiy ishlaydi.

## 11. Musobaqa Uchun To'g'ri Prioritet

Quyidagi tartib tavsiya qilinadi:

1. manual control stabil
2. stop va safety stabil
3. 3 kamera stabil
4. flower detection stabil
5. spray stabil
6. dashboard professional ko'rinishda
7. faqat shundan keyin autonomy

## 12. Demo Ssenariy

Musobaqada yoki taqdimotda soft qismini ko'rsatish uchun tavsiya etilgan ssenariy:

1. Dashboard ishga tushiriladi
2. 3 ta kamera ko'rinadi
3. ESP32 holati ko'rsatiladi
4. Telefon orqali manual yurish ko'rsatiladi
5. Kompyuterda diagnostics ko'rsatiladi
6. Front, chap yoki o'ng kameraga gul ko'rsatiladi
7. Detection box va center line ko'rsatiladi
8. Spray trigger bo'ladi
9. Emergency stop ko'rsatiladi
10. Agar vaqt bo'lsa autonomy preview ko'rsatiladi

## 13. Musobaqa Oldi Test Checklist

### 13.1. Hardware Checklist

- ESP32 firmware final versiya yozilgan
- motor driver ulanishlari tekshirilgan
- relay yoki MOSFET ulanishlari tekshirilgan
- nasoslar alohida quvvat bilan ishlayapti
- GND common tekshirilgan
- kameralar USB'da mustahkam turibdi
- laptop power stabil

### 13.2. Software Checklist

- config final
- left/right/front camera mapping final
- YOLO model yuklanadi
- web app telefonda ochiladi
- web app kompyuterda ochiladi
- stop ishlaydi
- stale command muammosi yo'q
- logs ko'rinadi

### 13.3. Functional Checklist

- oldinga ishlaydi
- orqaga ishlaydi
- chapga ishlaydi
- o'ngga ishlaydi
- tugmani qo'yib yuborganda stop
- speed slider ishlaydi
- left detection ishlaydi
- front detection ishlaydi
- right detection ishlaydi
- left pump ishlaydi
- front pump ishlaydi
- right pump ishlaydi
- auto spray toggle ishlaydi

### 13.4. Competition Day Checklist

- barcha kabel va quvvat tekshirildi
- laptop zaryadlangan
- brauzer cache tozalangan yoki final refresh qilingan
- Wi-Fi ulanish tasdiqlangan
- emergency stop sinovdan o'tgan
- 2-3 minutlik dry-run qilingan

## 14. Yakuniy Xulosa

Ushbu loyiha uchun mukammal soft degani:

- chiroyli interfeys
- tushunarli dashboard
- stabil manual control
- xavfsiz stop mexanizmi
- ishonchli spray logikasi
- kuzatiladigan hardware holati
- keyinchalik kengayadigan autonomy arxitekturasi

Musobaqa nuqtai nazaridan eng muhim narsa:

- tizim ishlashi
- operatorga tushunarli bo'lishi
- xatoda xavfsiz tutishi
- hakamga professional ko'rinishi

Shuning uchun yakuniy tavsiya:

- yangi feature qo'shishdan ko'ra stabilizatsiya ustun
- har bir holat ekranda ko'rinsin
- demonstration flow oldindan mashq qilinsin
- manual + smart spray + diagnostics kombinatsiyasi asosiy kuchli tomonga aylantirilsin
