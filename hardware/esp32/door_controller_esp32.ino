/*
 * Study Cafe Door Controller — ESP32
 * 전용 QR 스캐너 모듈(GM-65S 등)로 QR 데이터를 읽어
 * WiFi로 서버 API 호출 → 릴레이 제어로 도어락 개폐
 *
 * 하드웨어 연결:
 *   - ESP32 개발보드
 *   - QR 스캐너 모듈 (GM-65S, LV1 등) — Serial2 (GPIO16=RX, GPIO17=TX)
 *   - 릴레이 모듈 → GPIO 25
 *   - LED 녹색 → GPIO 26 (성공)
 *   - LED 적색 → GPIO 27 (실패)
 *   - 부저 → GPIO 14 (선택)
 *   - OLED SSD1306 → I2C (GPIO21=SDA, GPIO22=SCL) (선택)
 *
 * 라이브러리 (Arduino IDE):
 *   - WiFi.h (내장)
 *   - HTTPClient.h (내장)
 *   - ArduinoJson by Benoit Blanchon
 *   - (선택) Adafruit SSD1306, Adafruit GFX
 *
 * 업로드 후 시리얼 모니터(115200 baud)에서 WiFi 연결 상태 확인
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ============ 설정 ============
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL    = "http://192.168.0.10:5000";  // Flask 서버 주소

// 핀 설정
const int RELAY_PIN   = 25;
const int LED_GREEN   = 26;
const int LED_RED     = 27;
const int BUZZER_PIN  = 14;

// 동작 설정
const int DOOR_OPEN_MS     = 3000;   // 문 열림 유지 시간 (ms)
const int COOLDOWN_MS      = 5000;   // 같은 QR 재스캔 방지 (ms)
const int API_TIMEOUT_MS   = 10000;  // API 타임아웃 (ms)

// ============ 전역 변수 ============
String lastToken = "";
unsigned long lastScanTime = 0;
String qrBuffer = "";

// ============ 초기화 ============
void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, 16, 17);  // QR 스캐너용 Serial2

  // 핀 설정
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  Serial.println("\n=============================");
  Serial.println("  Study Cafe Door Controller");
  Serial.println("  ESP32 + QR Scanner");
  Serial.println("=============================");

  // WiFi 연결
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi 연결 중");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi 연결됨. IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("서버: ");
  Serial.println(SERVER_URL);
  Serial.println("\nQR 코드를 스캔하세요...\n");
}

// ============ 메인 루프 ============
void loop() {
  // QR 스캐너에서 데이터 읽기
  while (Serial2.available()) {
    char c = Serial2.read();
    if (c == '\n' || c == '\r') {
      if (qrBuffer.length() > 0) {
        processQR(qrBuffer);
        qrBuffer = "";
      }
    } else {
      qrBuffer += c;
    }
  }
  delay(10);
}

// ============ QR 처리 ============
void processQR(String rawData) {
  // QR 데이터에서 토큰 추출
  // 형식: http://서버/qr/scan?token=xxx  또는  단순 토큰
  String token = extractToken(rawData);
  if (token.length() == 0) {
    Serial.println("QR: 토큰 추출 실패");
    signalError();
    return;
  }

  Serial.print("QR 인식: ");
  Serial.println(token.substring(0, 20) + "...");

  // 쿨다운 체크
  unsigned long now = millis();
  if (token == lastToken && (now - lastScanTime) < COOLDOWN_MS) {
    Serial.println("  (쿨다운 - 무시)");
    return;
  }
  lastToken = token;
  lastScanTime = now;

  // 1단계: 토큰 검증 → 입실/출실 판단
  String action = verifyToken(token);
  if (action.length() == 0) {
    Serial.println("  검증 실패 - 서버 연결 확인");
    signalError();
    return;
  }
  if (action == "error") {
    Serial.println("  유효하지 않은 QR");
    signalError();
    return;
  }

  Serial.print("  → ");
  Serial.print(action == "checkin" ? "입실" : "출실");
  Serial.println(" 처리 중...");

  // 2단계: 입실/출실 API 호출
  bool success = callDoorAPI(token, action);
  if (success) {
    Serial.println("  성공! 문 개방");
    signalSuccess();
    doorOpen();
  } else {
    Serial.println("  실패!");
    signalError();
  }
}

// ============ 토큰 추출 ============
String extractToken(String data) {
  data.trim();
  int idx = data.indexOf("token=");
  if (idx >= 0) {
    String t = data.substring(idx + 6);
    int amp = t.indexOf('&');
    if (amp >= 0) t = t.substring(0, amp);
    t.trim();
    return t;
  }
  return data;
}

// ============ 서버 API: 검증 ============
String verifyToken(String token) {
  if (WiFi.status() != WL_CONNECTED) return "";

  HTTPClient http;
  String url = String(SERVER_URL) + "/api/door/verify";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(API_TIMEOUT_MS);

  String body = "{\"token\":\"" + token + "\"}";
  int code = http.POST(body);

  if (code <= 0) {
    http.end();
    return "";
  }

  String response = http.getString();
  http.end();

  // JSON 파싱
  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, response);
  if (err) return "";

  bool success = doc["success"] | false;
  if (!success) return "error";

  String action = doc["action"] | "";
  if (action == "checkin_ready") return "checkin";
  if (action == "checkout_ready") return "checkout";
  return "error";
}

// ============ 서버 API: 입실/출실 ============
bool callDoorAPI(String token, String action) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  String url = String(SERVER_URL) + "/api/door/" + action;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(API_TIMEOUT_MS);

  String body = "{\"token\":\"" + token + "\"}";
  int code = http.POST(body);

  if (code <= 0) {
    http.end();
    return false;
  }

  String response = http.getString();
  http.end();

  Serial.print("  응답: ");
  Serial.println(response);

  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, response);
  if (err) return false;

  return doc["success"] | false;
}

// ============ 하드웨어 제어 ============
void doorOpen() {
  digitalWrite(RELAY_PIN, HIGH);
  Serial.println("🚪 문 열림");
  delay(DOOR_OPEN_MS);
  digitalWrite(RELAY_PIN, LOW);
  Serial.println("🔒 문 닫힘");
}

void signalSuccess() {
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(BUZZER_PIN, HIGH);
  delay(300);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
}

void signalError() {
  for (int i = 0; i < 2; i++) {
    digitalWrite(LED_RED, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(200);
    digitalWrite(LED_RED, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    delay(150);
  }
}