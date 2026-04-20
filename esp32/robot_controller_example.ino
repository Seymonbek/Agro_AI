/*
  Flower Rover ESP32 Controller
  --------------------------------
  Bu fayl sizning robot uchun to'liq ESP32 firmware.

  Vazifalari:
  1. Ikkita BTS7960 driver orqali tank usulida harakatlantirish
  2. 2 ta nasos chiqishini boshqarish
  3. Wi-Fi Access Point ko'tarish
  4. Laptop server uchun HTTP API berish
  5. Eski /F /B /L /R /S buyruqlarini ham qo'llab-quvvatlash
  6. Failsafe: buyruq kelmay qolsa motorni to'xtatish

  MUHIM:
  - Motor pinlari siz yuborgan kod bo'yicha qoldirildi.
  - Nasos pinlari bu yerda xavfsiz tavsiya pinlarga qo'yildi.
    Agar hardware allaqachon boshqa pinlarga ulangan bo'lsa, shu 2 ta #define ni o'zgartiring.

  TIZIM MANTIGI:
  - Chap kamera gul markazini topsa -> chap nasos ishlaydi
  - O'ng kamera gul markazini topsa -> o'ng nasos ishlaydi
  - Old kamera NASOSGA ulanmaydi, u faqat yo'lni ko'rish uchun

  ESlATMA:
  - Bu kod ESP32 tomonidagi "bajaruvchi" qism.
  - Laptop server esa Wi-Fi orqali /api/drive va /api/pump endpointlariga so'rov yuboradi.
*/

#include <WebServer.h>
#include <WiFi.h>

// =========================================================
// Wi-Fi Access Point sozlamalari
// Laptop shu Wi-Fi ga ulanadi va ESP32 bilan gaplashadi.
// Demak ESP32 o'zi modem vazifasini bajaradi.
// =========================================================
const char *AP_SSID = "123";
const char *AP_PASSWORD = "12345678";

// =========================================================
#define LEFT_RPWM 25
#define LEFT_LPWM 26
#define LEFT_REN 33
#define LEFT_LEN 32


#define RIGHT_RPWM 27
#define RIGHT_LPWM 14
#define RIGHT_REN 18
#define RIGHT_LEN 19


#define PUMP_LEFT_PIN 16
#define PUMP_RIGHT_PIN 17

// Agar relay HIGH signal bilan ishlasa true.
// Agar relay LOW signal bilan ishlasa false.
const bool PUMP_ACTIVE_HIGH = true;

int speedLimit = 120;                 // Asosiy tezlik limiti: 0..255
const int MIN_EFFECTIVE_PWM = 55;     // Juda kichik PWM da motor qimirlamasa shu pastki chegara ishlaydi
const float INPUT_DEADZONE = 0.08f;   // Juda mayda buyruqlarni ignore qilamiz
const float RAMP_STEP_UP = 0.045f;    // Start paytida silliq tezlashish
const float RAMP_STEP_DOWN = 0.09f;   // To'xtash yoki sekinlashish tezroq bo'lsin
const unsigned long RAMP_INTERVAL_MS = 25;
const unsigned long MOTOR_FAILSAFE_MS = 1200;
// Agar 1200 ms davomida yangi harakat buyrug'i kelmasa motor avtomatik to'xtaydi.

WebServer server(80);
unsigned long lastDriveCommandMs = 0;
unsigned long lastRampUpdateMs = 0;
bool motorsAreMoving = false;
float targetLeftNormalized = 0.0f;
float targetRightNormalized = 0.0f;
float currentLeftNormalized = 0.0f;
float currentRightNormalized = 0.0f;

// 0.0..1.0 diapazondagi qiymatni 0..255 PWM ga aylantiradi.
// Juda kichik qiymat bo'lsa motor umuman qimirlamaydi.
int scaleToPwm(float valueNormalized) {
  float magnitude = abs(valueNormalized);
  if (magnitude < INPUT_DEADZONE) {
    return 0;
  }

  int pwm = (int)(magnitude * speedLimit);
  if (speedLimit >= MIN_EFFECTIVE_PWM && pwm > 0 && pwm < MIN_EFFECTIVE_PWM) {
    pwm = MIN_EFFECTIVE_PWM;
  }
  return constrain(pwm, 0, 255);
}

// Nasos relay/MOSFET signal piniga yozish.
void writePumpPin(int pin, bool enabled) {
  digitalWrite(pin, enabled == PUMP_ACTIVE_HIGH ? HIGH : LOW);
}

// Qaysi nasos yoqilishini tanlaydi.
void setPumpState(const String &side, bool enabled) {
  if (side == "left") {
    writePumpPin(PUMP_LEFT_PIN, enabled);
  } else if (side == "right") {
    writePumpPin(PUMP_RIGHT_PIN, enabled);
  }
}

// Barcha nasoslarni xavfsizlik uchun o'chiradi.
void disableAllPumps() {
  writePumpPin(PUMP_LEFT_PIN, false);
  writePumpPin(PUMP_RIGHT_PIN, false);
}

// Barcha motorlarni to'xtatadi.
void stopMotors() {
  targetLeftNormalized = 0.0f;
  targetRightNormalized = 0.0f;
  currentLeftNormalized = 0.0f;
  currentRightNormalized = 0.0f;
  analogWrite(LEFT_RPWM, 0);
  analogWrite(LEFT_LPWM, 0);
  analogWrite(RIGHT_RPWM, 0);
  analogWrite(RIGHT_LPWM, 0);
  motorsAreMoving = false;
}

// Bitta tomonni oldinga yoki orqaga aylantirish.
// normalizedValue:
//   musbat  -> oldinga
//   manfiy  -> orqaga
//   0 ga yaqin -> stop
void writeSidePwm(int rpwmPin, int lpwmPin, float normalizedValue) {
  int pwm = scaleToPwm(normalizedValue);

  if (normalizedValue > INPUT_DEADZONE) {
    analogWrite(rpwmPin, 0);
    analogWrite(lpwmPin, pwm);
  } else if (normalizedValue < -INPUT_DEADZONE) {
    analogWrite(rpwmPin, pwm);
    analogWrite(lpwmPin, 0);
  } else {
    analogWrite(rpwmPin, 0);
    analogWrite(lpwmPin, 0);
  }
}

float moveToward(float currentValue, float targetValue, float stepSize) {
  if (targetValue > currentValue) {
    return min(currentValue + stepSize, targetValue);
  }
  if (targetValue < currentValue) {
    return max(currentValue - stepSize, targetValue);
  }
  return currentValue;
}

float selectRampStep(float currentValue, float targetValue) {
  if ((currentValue > 0.0f && targetValue < 0.0f) || (currentValue < 0.0f && targetValue > 0.0f)) {
    return RAMP_STEP_DOWN;
  }
  if (abs(targetValue) > abs(currentValue)) {
    return RAMP_STEP_UP;
  }
  return RAMP_STEP_DOWN;
}

void updateMotorOutputs() {
  writeSidePwm(LEFT_RPWM, LEFT_LPWM, currentLeftNormalized);
  writeSidePwm(RIGHT_RPWM, RIGHT_LPWM, currentRightNormalized);
  motorsAreMoving =
      (abs(currentLeftNormalized) > INPUT_DEADZONE || abs(currentRightNormalized) > INPUT_DEADZONE ||
       abs(targetLeftNormalized) > INPUT_DEADZONE || abs(targetRightNormalized) > INPUT_DEADZONE);
}

// Tank boshqaruv:
// leftNormalized  -> chap g'ildiraklar guruhi
// rightNormalized -> o'ng g'ildiraklar guruhi
//
// Misol:
// ( 1,  1) -> oldinga
// (-1, -1) -> orqaga
// ( 1, -1) -> joyida chapga burilish
// (-1,  1) -> joyida o'ngga burilish
void applyTankDrive(float leftNormalized, float rightNormalized) {
  targetLeftNormalized = constrain(leftNormalized, -1.0f, 1.0f);
  targetRightNormalized = constrain(rightNormalized, -1.0f, 1.0f);
  lastDriveCommandMs = millis();
}

void updateDriveRamp() {
  if (millis() - lastRampUpdateMs < RAMP_INTERVAL_MS) {
    return;
  }

  lastRampUpdateMs = millis();
  currentLeftNormalized = moveToward(
      currentLeftNormalized,
      targetLeftNormalized,
      selectRampStep(currentLeftNormalized, targetLeftNormalized));
  currentRightNormalized = moveToward(
      currentRightNormalized,
      targetRightNormalized,
      selectRampStep(currentRightNormalized, targetRightNormalized));
  updateMotorOutputs();
}

// BTS7960 driver enable pinlarini doim yoqib qo'yamiz.
void setEnablePins() {
  digitalWrite(LEFT_REN, HIGH);
  digitalWrite(LEFT_LEN, HIGH);
  digitalWrite(RIGHT_REN, HIGH);
  digitalWrite(RIGHT_LEN, HIGH);
}

// Laptop server uchun status JSON qaytariladi.
String buildStatusJson() {
  String json = "{";
  json += "\"ok\":true,";
  json += "\"mode\":\"advanced\",";
  json += "\"ip\":\"" + WiFi.softAPIP().toString() + "\",";
  json += "\"ssid\":\"" + String(AP_SSID) + "\",";
  json += "\"speedLimit\":" + String(speedLimit) + ",";
  json += "\"failsafeMs\":" + String(MOTOR_FAILSAFE_MS) + ",";
  json += "\"uptimeMs\":" + String(millis());
  json += "}";
  return json;
}

void sendStatus() {
  server.send(200, "application/json", buildStatusJson());
}

// ADVANCED API
// Laptop server shu endpointlardan foydalanadi.
//
// Endpointlar:
// /api/status
// /api/speed?value=180
// /api/drive?left=0.7&right=0.7&speed=180
// /api/pump?side=left&state=on
// /api/stop
void handleApiStatus() {
  sendStatus();
}

// Tezlik limitini o'zgartirish.
void handleApiSpeed() {
  if (server.hasArg("value")) {
    speedLimit = constrain(server.arg("value").toInt(), 0, 255);
  }
  sendStatus();
}

// Asosiy harakat endpointi.
// left/right -1.0 dan 1.0 gacha bo'ladi.
void handleApiDrive() {
  float left = server.hasArg("left") ? server.arg("left").toFloat() : 0.0f;
  float right = server.hasArg("right") ? server.arg("right").toFloat() : 0.0f;

  if (server.hasArg("speed")) {
    speedLimit = constrain(server.arg("speed").toInt(), 0, 255);
  }

  applyTankDrive(left, right);
  sendStatus();
}

// Nasosni yoqish/o'chirish endpointi.
// side = left yoki right
// state = on yoki off
void handleApiPump() {
  String side = server.hasArg("side") ? server.arg("side") : "left";
  bool enabled = server.hasArg("state") && server.arg("state") == "on";
  if (side != "left" && side != "right") {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid_pump_side\"}");
    return;
  }
  setPumpState(side, enabled);
  sendStatus();
}

// Zudlik bilan motorni to'xtatish endpointi.
void handleApiStop() {
  stopMotors();
  sendStatus();
}

// =========================================================
// LEGACY ENDPOINTLAR
// Eski test va qo'lda tekshirish uchun qoldirildi.
// Brauzerda IP manzilni ochib /F /B /L /R /S ni urib sinasa ham bo'ladi.
// =========================================================
void handleForward() {
  applyTankDrive(1.0f, 1.0f);
  server.send(200, "text/plain", "FORWARD");
}

void handleBackward() {
  applyTankDrive(-1.0f, -1.0f);
  server.send(200, "text/plain", "BACKWARD");
}

void handleLeft() {
  applyTankDrive(1.0f, -1.0f);
  server.send(200, "text/plain", "LEFT");
}

void handleRight() {
  applyTankDrive(-1.0f, 1.0f);
  server.send(200, "text/plain", "RIGHT");
}

void handleStopLegacy() {
  stopMotors();
  server.send(200, "text/plain", "STOP");
}

void handleRoot() {
  String html = "";
  html += "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<style>";
  html += "body{font-family:Arial;text-align:center;background:#f2f2f2;margin-top:40px;}";
  html += "button{width:110px;height:60px;font-size:18px;margin:8px;border:none;border-radius:12px;}";
  html += "</style></head><body>";
  html += "<h2>Flower Rover ESP32</h2>";
  html += "<p>IP: " + WiFi.softAPIP().toString() + "</p>";
  html += "<p><a href='/F'><button>Oldinga</button></a></p>";
  html += "<p><a href='/L'><button>Chap</button></a> <a href='/S'><button>Stop</button></a> <a href='/R'><button>O'ng</button></a></p>";
  html += "<p><a href='/B'><button>Orqaga</button></a></p>";
  html += "<p><a href='/api/status'><button>Status JSON</button></a></p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

// Noma'lum endpoint kelsa JSON xato qaytaradi.
void handleNotFound() {
  server.send(404, "application/json", "{\"ok\":false,\"error\":\"not_found\"}");
}

// =========================================================
// SETUP
// =========================================================
void setup() {
  Serial.begin(115200);

  // Motor pinlarini chiqish rejimiga o'tkazish
  pinMode(LEFT_RPWM, OUTPUT);
  pinMode(LEFT_LPWM, OUTPUT);
  pinMode(LEFT_REN, OUTPUT);
  pinMode(LEFT_LEN, OUTPUT);

  pinMode(RIGHT_RPWM, OUTPUT);
  pinMode(RIGHT_LPWM, OUTPUT);
  pinMode(RIGHT_REN, OUTPUT);
  pinMode(RIGHT_LEN, OUTPUT);

  // Nasos chiqish pinlari
  pinMode(PUMP_LEFT_PIN, OUTPUT);
  pinMode(PUMP_RIGHT_PIN, OUTPUT);

  // Qurilma yoqilganda xavfsiz holat:
  // driver enable yoqilgan, motor stop, nasoslar off
  setEnablePins();
  stopMotors();
  disableAllPumps();
  lastDriveCommandMs = millis();
  lastRampUpdateMs = millis();

  // ESP32 o'zi Wi-Fi nuqta bo'ladi
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASSWORD);

  // Asosiy web sahifa
  server.on("/", handleRoot);

  // Advanced API - laptop server shu bilan ishlaydi
  server.on("/api/status", handleApiStatus);
  server.on("/api/speed", handleApiSpeed);
  server.on("/api/drive", handleApiDrive);
  server.on("/api/pump", handleApiPump);
  server.on("/api/stop", handleApiStop);

  // Legacy API - qo'lda browser test uchun
  server.on("/F", handleForward);
  server.on("/B", handleBackward);
  server.on("/L", handleLeft);
  server.on("/R", handleRight);
  server.on("/S", handleStopLegacy);

  server.onNotFound(handleNotFound);
  server.begin();

  // Serial monitor ga kerakli ma'lumotlarni chiqarish
  Serial.println("====================================");
  Serial.println("Flower Rover ESP32 ready");
  Serial.print("SSID: ");
  Serial.println(AP_SSID);
  Serial.print("Password: ");
  Serial.println(AP_PASSWORD);
  Serial.print("AP IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("====================================");
}

// =========================================================
// LOOP
// =========================================================
void loop() {
  // Har bir kelgan HTTP so'rovni qabul qiladi
  server.handleClient();

  // Tezlikni birdan emas, silliq ko'taradi/tushiradi.
  updateDriveRamp();

  // Failsafe: buyruq kelmay qolsa motorni o'zi to'xtatadi
  if (motorsAreMoving && millis() - lastDriveCommandMs > MOTOR_FAILSAFE_MS) {
    stopMotors();
  }
}
