/*
  Flower Rover ESP32 Controller
  --------------------------------
  Bu fayl sizning robot uchun to'liq ESP32 firmware.

  Vazifalari:
  1. Ikkita BTS7960 driver orqali tank usulida harakatlantirish
  2. Spray chiqishlarini boshqarish
  3. Wi-Fi Access Point ko'tarish
  4. Laptop server uchun HTTP API berish
  5. Eski /F /B /L /R /S buyruqlarini ham qo'llab-quvvatlash
  6. Failsafe: buyruq kelmay qolsa motorni to'xtatish

  MUHIM:
  - Motor pinlari siz yuborgan kod bo'yicha qoldirildi.
  - Nasos pinlari bu yerda xavfsiz tavsiya pinlarga qo'yildi.
    Agar hardware allaqachon boshqa pinlarga ulangan bo'lsa, shu #define larni o'zgartiring.
  - Hozirgi default soft config `front` kameradan detect qilib `left + right` spray kanalini yoqadi.
  - Firmware ichida old/front chiqish ham saqlangan: left=GPIO16, front=GPIO23, right=GPIO17.
    Agar sizda faqat 2 ta nasos bo'lsa `front` pinni ulash shart emas.

  TIZIM MANTIGI:
  - Hozirgi default rejimda old kamera gul markazini topsa -> chap va o'ng spray ishlaydi
  - Chap va o'ng kameralar asosan operator monitoring uchun ishlatiladi
  - Agar keyin alohida front valve kerak bo'lsa firmware ichidagi `front` kanalni yoqish mumkin

  ESlATMA:
  - Bu kod ESP32 tomonidagi "bajaruvchi" qism.
  - Laptop server esa Wi-Fi orqali /api/drive va /api/pump endpointlariga so'rov yuboradi.
*/

#include <WebServer.h>
#include <WiFi.h>
#include <ctype.h>
#include <stdio.h>
#include <string.h>

// =========================================================
// Wi-Fi Access Point sozlamalari
// Laptop shu Wi-Fi ga ulanadi va ESP32 bilan gaplashadi.
// Demak ESP32 o'zi modem vazifasini bajaradi.
// =========================================================
// USB serial ishlatilsa false qiling. Bu ESP32 qizishini kamaytiradi.
// Wi-Fi HTTP fallback kerak bo'lsa true qiling.
const bool ENABLE_WIFI_AP = false;
const char *AP_SSID = "123";
const char *AP_PASSWORD = "12345678";
const uint8_t AP_CHANNEL = 6;
const uint8_t AP_MAX_CONNECTIONS = 4;
const unsigned long AP_HEALTHCHECK_MS = 5000;
IPAddress AP_IP(192, 168, 4, 1);
IPAddress AP_GATEWAY(192, 168, 4, 1);
IPAddress AP_SUBNET(255, 255, 255, 0);

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
#define PUMP_FRONT_PIN 23
#define PUMP_RIGHT_PIN 17

// Agar relay HIGH signal bilan ishlasa true.
// Agar relay LOW signal bilan ishlasa false.
const bool PUMP_ACTIVE_HIGH = false;

int speedLimit = 120;                 // Asosiy tezlik limiti: 0..255
const int MIN_EFFECTIVE_PWM = 55;     // Juda kichik PWM da motor qimirlamasa shu pastki chegara ishlaydi
const float INPUT_DEADZONE = 0.08f;   // Juda mayda buyruqlarni ignore qilamiz
const float RAMP_STEP_UP = 0.08f;     // Qo'lda boshqaruv sezgir bo'lishi uchun tezroq tezlashish
const float RAMP_STEP_DOWN = 0.12f;   // Yo'nalish almashtirish va to'xtashda chaqqonroq javob
const unsigned long RAMP_INTERVAL_MS = 20;
const unsigned long MOTOR_FAILSAFE_MS = 1200;
const size_t SERIAL_LINE_BUFFER_SIZE = 96;
const size_t STATUS_JSON_BUFFER_SIZE = 256;
// Agar 1200 ms davomida yangi harakat buyrug'i kelmasa motor avtomatik to'xtaydi.

WebServer server(80);
unsigned long lastDriveCommandMs = 0;
unsigned long lastRampUpdateMs = 0;
unsigned long lastApHealthcheckMs = 0;
bool motorsAreMoving = false;
bool pumpLeftState = false;
bool pumpFrontState = false;
bool pumpRightState = false;
float targetLeftNormalized = 0.0f;
float targetRightNormalized = 0.0f;
float currentLeftNormalized = 0.0f;
float currentRightNormalized = 0.0f;
char serialLineBuffer[SERIAL_LINE_BUFFER_SIZE];
size_t serialLineLength = 0;

// 0.0..1.0 diapazondagi qiymatni 0..255 PWM ga aylantiradi.
// Juda kichik qiymat bo'lsa motor umuman qimirlamaydi.
int scaleToPwm(float valueNormalized) {
  float magnitude = abs(valueNormalized);
  if (magnitude < INPUT_DEADZONE) {
    return 0;
  }

  int pwm = (int)(magnitude * speedLimit);
  if (pwm > 0 && pwm < MIN_EFFECTIVE_PWM) {
    pwm = MIN_EFFECTIVE_PWM;
  }
  return constrain(pwm, 0, 255);
}

// Nasos relay/MOSFET signal piniga yozish.
void writePumpPin(int pin, bool enabled) {
  digitalWrite(pin, enabled == PUMP_ACTIVE_HIGH ? HIGH : LOW);
}

// Qaysi nasos yoqilishini tanlaydi.
void setPumpState(const char *side, bool enabled) {
  if (strcmp(side, "left") == 0) {
    pumpLeftState = enabled;
    writePumpPin(PUMP_LEFT_PIN, enabled);
  } else if (strcmp(side, "front") == 0) {
    pumpFrontState = enabled;
    writePumpPin(PUMP_FRONT_PIN, enabled);
  } else if (strcmp(side, "right") == 0) {
    pumpRightState = enabled;
    writePumpPin(PUMP_RIGHT_PIN, enabled);
  }
}

// Barcha nasoslarni xavfsizlik uchun o'chiradi.
void disableAllPumps() {
  setPumpState("left", false);
  setPumpState("front", false);
  setPumpState("right", false);
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
void buildStatusJson(char *buffer, size_t bufferSize) {
  String ipString = WiFi.softAPIP().toString();
  snprintf(
      buffer,
      bufferSize,
      "{\"ok\":true,\"mode\":\"advanced\",\"transport\":\"serial-http\",\"wifiAp\":%s,"
      "\"ip\":\"%s\",\"ssid\":\"%s\",\"speedLimit\":%d,\"failsafeMs\":%lu,"
      "\"pumps\":{\"left\":%s,\"front\":%s,\"right\":%s},\"uptimeMs\":%lu}",
      ENABLE_WIFI_AP ? "true" : "false",
      ipString.c_str(),
      AP_SSID,
      speedLimit,
      MOTOR_FAILSAFE_MS,
      pumpLeftState ? "true" : "false",
      pumpFrontState ? "true" : "false",
      pumpRightState ? "true" : "false",
      millis());
}

void sendStatus() {
  char buffer[STATUS_JSON_BUFFER_SIZE];
  buildStatusJson(buffer, sizeof(buffer));
  server.send(200, "application/json", buffer);
}

// Wi-Fi AP ni barqaror ushlash: fixed IP, aniq channel, sleep off.
bool startAccessPoint() {
  WiFi.persistent(false);
  WiFi.setSleep(false);
  WiFi.mode(WIFI_AP);
  delay(150);
  WiFi.softAPConfig(AP_IP, AP_GATEWAY, AP_SUBNET);
  return WiFi.softAP(AP_SSID, AP_PASSWORD, AP_CHANNEL, 0, AP_MAX_CONNECTIONS);
}

// ADVANCED API
// Laptop server shu endpointlardan foydalanadi.
//
// Endpointlar:
// /api/status
// /api/speed?value=180
// /api/drive?left=0.7&right=0.7&speed=180
// /api/pump?side=left&state=on
// /api/pump?side=front&state=on
// /api/pump?side=right&state=on
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
// side = left, front yoki right
// state = on yoki off
void handleApiPump() {
  String side = server.hasArg("side") ? server.arg("side") : "left";
  bool enabled = server.hasArg("state") && server.arg("state") == "on";
  if (side != "left" && side != "front" && side != "right") {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid_pump_side\"}");
    return;
  }
  setPumpState(side.c_str(), enabled);
  sendStatus();
}

// Zudlik bilan motorni to'xtatish endpointi.
void handleApiStop() {
  stopMotors();
  disableAllPumps();
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
  disableAllPumps();
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
  html += "<p><a href='/api/pump?side=left&state=on'><button>Left ON</button></a> ";
  html += "<a href='/api/pump?side=front&state=on'><button>Front ON</button></a> ";
  html += "<a href='/api/pump?side=right&state=on'><button>Right ON</button></a></p>";
  html += "<p><a href='/api/pump?side=left&state=off'><button>Left OFF</button></a> ";
  html += "<a href='/api/pump?side=front&state=off'><button>Front OFF</button></a> ";
  html += "<a href='/api/pump?side=right&state=off'><button>Right OFF</button></a></p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

// Noma'lum endpoint kelsa JSON xato qaytaradi.
void handleNotFound() {
  server.send(404, "application/json", "{\"ok\":false,\"error\":\"not_found\"}");
}

// =========================================================
// USB SERIAL API
// Notebook miya bo'lganda Python server ESP32 bilan shu buyruqlar orqali gaplashadi.
//
// STATUS
// SPEED 180
// DRIVE 0.700 0.700 180
// PUMP left on
// PUMP front off
// STOP
// =========================================================
void trimWhitespace(char *text) {
  size_t start = 0;
  size_t length = strlen(text);
  while (start < length && isspace((unsigned char)text[start])) {
    start++;
  }
  while (length > start && isspace((unsigned char)text[length - 1])) {
    length--;
  }
  if (start > 0) {
    memmove(text, text + start, length - start);
  }
  text[length - start] = '\0';
}

void toUpperInPlace(char *text) {
  while (*text != '\0') {
    *text = (char)toupper((unsigned char)*text);
    text++;
  }
}

void toLowerInPlace(char *text) {
  while (*text != '\0') {
    *text = (char)tolower((unsigned char)*text);
    text++;
  }
}

void sendSerialStatus() {
  char buffer[STATUS_JSON_BUFFER_SIZE];
  buildStatusJson(buffer, sizeof(buffer));
  Serial.println(buffer);
}

void sendSerialError(const char *errorCode) {
  Serial.print("{\"ok\":false,\"error\":\"");
  Serial.print(errorCode);
  Serial.println("\"}");
}

void handleSerialCommand(char *line) {
  trimWhitespace(line);
  if (line[0] == '\0') {
    return;
  }

  char *context = nullptr;
  char *command = strtok_r(line, " ", &context);
  if (command == nullptr) {
    return;
  }
  toUpperInPlace(command);

  if (strcmp(command, "STATUS") == 0 || strcmp(command, "PING") == 0) {
    sendSerialStatus();
    return;
  }

  if (strcmp(command, "SPEED") == 0) {
    char *value = strtok_r(nullptr, " ", &context);
    if (value == nullptr) {
      sendSerialError("missing_speed");
      return;
    }
    speedLimit = constrain(atoi(value), 0, 255);
    sendSerialStatus();
    return;
  }

  if (strcmp(command, "DRIVE") == 0) {
    char *leftToken = strtok_r(nullptr, " ", &context);
    char *rightToken = strtok_r(nullptr, " ", &context);
    char *speedToken = strtok_r(nullptr, " ", &context);
    if (leftToken == nullptr || rightToken == nullptr) {
      sendSerialError("missing_drive_values");
      return;
    }
    if (speedToken != nullptr && speedToken[0] != '\0') {
      speedLimit = constrain(atoi(speedToken), 0, 255);
    }
    applyTankDrive((float)atof(leftToken), (float)atof(rightToken));
    sendSerialStatus();
    return;
  }

  if (strcmp(command, "PUMP") == 0) {
    char *side = strtok_r(nullptr, " ", &context);
    char *state = strtok_r(nullptr, " ", &context);
    if (side == nullptr || state == nullptr) {
      sendSerialError("invalid_pump_state");
      return;
    }
    toLowerInPlace(side);
    toLowerInPlace(state);
    if (strcmp(side, "left") != 0 && strcmp(side, "front") != 0 && strcmp(side, "right") != 0) {
      sendSerialError("invalid_pump_side");
      return;
    }
    if (strcmp(state, "on") != 0 && strcmp(state, "off") != 0) {
      sendSerialError("invalid_pump_state");
      return;
    }
    setPumpState(side, strcmp(state, "on") == 0);
    sendSerialStatus();
    return;
  }

  if (strcmp(command, "STOP") == 0) {
    stopMotors();
    disableAllPumps();
    sendSerialStatus();
    return;
  }

  sendSerialError("unknown_command");
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    char incoming = (char)Serial.read();
    if (incoming == '\r') {
      continue;
    }

    if (incoming == '\n') {
      serialLineBuffer[serialLineLength] = '\0';
      handleSerialCommand(serialLineBuffer);
      serialLineLength = 0;
      continue;
    }

    if (serialLineLength < (SERIAL_LINE_BUFFER_SIZE - 1)) {
      serialLineBuffer[serialLineLength++] = incoming;
    } else {
      serialLineLength = 0;
      sendSerialError("line_too_long");
    }
  }
}

// =========================================================
// SETUP
// =========================================================
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(20);

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
  pinMode(PUMP_FRONT_PIN, OUTPUT);
  pinMode(PUMP_RIGHT_PIN, OUTPUT);

  // Qurilma yoqilganda xavfsiz holat:
  // driver enable yoqilgan, motor stop, nasoslar off
  setEnablePins();
  stopMotors();
  disableAllPumps();
  lastDriveCommandMs = millis();
  lastRampUpdateMs = millis();

  bool apOk = false;
  if (ENABLE_WIFI_AP) {
    // ESP32 o'zi Wi-Fi nuqta bo'ladi
    apOk = startAccessPoint();

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
  } else {
    WiFi.mode(WIFI_OFF);
  }

  // Serial monitor ga kerakli ma'lumotlarni chiqarish
  Serial.println("====================================");
  Serial.println("Flower Rover ESP32 ready");
  Serial.print("Transport: ");
  Serial.println(ENABLE_WIFI_AP ? "USB Serial + Wi-Fi HTTP" : "USB Serial only");
  Serial.print("AP started: ");
  Serial.println(apOk ? "YES" : "NO");
  if (ENABLE_WIFI_AP) {
    Serial.print("SSID: ");
    Serial.println(AP_SSID);
    Serial.print("AP IP: ");
    Serial.println(WiFi.softAPIP());
  }
  Serial.println("====================================");
}

// =========================================================
// LOOP
// =========================================================
void loop() {
  handleSerialCommands();

  if (ENABLE_WIFI_AP) {
    // Har bir kelgan HTTP so'rovni qabul qiladi
    server.handleClient();

    // Wi-Fi AP tushib qolsa qayta ko'taramiz.
    if (millis() - lastApHealthcheckMs > AP_HEALTHCHECK_MS) {
      lastApHealthcheckMs = millis();
      if (WiFi.getMode() != WIFI_AP || WiFi.softAPIP()[0] == 0) {
        Serial.println("Wi-Fi AP qayta ishga tushirilmoqda...");
        startAccessPoint();
      }
    }
  }

  // Tezlikni birdan emas, silliq ko'taradi/tushiradi.
  updateDriveRamp();

  // Failsafe: buyruq kelmay qolsa motorni o'zi to'xtatadi
  if (motorsAreMoving && millis() - lastDriveCommandMs > MOTOR_FAILSAFE_MS) {
    stopMotors();
  }
}
