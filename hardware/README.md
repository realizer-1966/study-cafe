# 출입문 QR 스캐너 장치 만들기

QR 코드를 읽고 출입문을 자동으로 개폐하는 장치의 제작 가이드입니다.

## 시스템 구성

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────┐
│  QR 스캐너   │────▶│  컨트롤러     │────▶│  Flask 서버  │────▶│  도어락   │
│             │     │              │     │  (app.py)    │     │           │
│ 카메라 또는 │     │ Raspberry Pi │     │  /api/door/  │     │ 솔레노이드 │
│ 전용 모듈   │     │ 또는 ESP32   │     │  checkin     │     │ 도어락    │
└─────────────┘     └──────────────┘     └──────────────┘     └───────────┘
                     HTTP POST JSON       입실/출실 처리        릴레이 제어
```

## 동작 순서

1. 사용자가 스마트폰의 QR 코드를 스캐너에 보여줌
2. 컨트롤러가 QR 데이터에서 토큰 추출
3. 서버 `/api/door/verify`로 토큰 검증 → 입실인지 출실인지 판단
4. 서버 `/api/door/checkin` 또는 `/api/door/checkout` 호출
5. 서버가 JSON으로 결과 반환
6. 성공 시 릴레이 ON → 도어락 해제 (3초 후 자동 잠금)
7. 실패 시 적색 LED + 부저 경고

---

## 방식 A: Raspberry Pi + 카메라 (DIY)

### 필요 부품

| 부품 | 설명 | 예상 가격 |
|------|------|-----------|
| Raspberry Pi 4B (2GB) | 메인 컨트롤러 | 5~7만 원 |
| Pi Camera V2 | QR 코드 촬영 | 1.5만 원 |
| 릴레이 모듈 (5V 1채널) | 도어락 제어 | 2천 원 |
| 12V 솔레노이드 도어락 | 물리적 잠금/해제 | 1~2만 원 |
| 12V 전원 어댑터 | 도어락용 | 5천 원 |
| 점퍼 와이어 | 연결용 | 2천 원 |
| (선택) LED + 저항 | 상태 표시 | 1천 원 |
| (선택) 부저 | 알람 | 1천 원 |
| **합계** | | **약 8~10만 원** |

### 배선도

```
Raspberry Pi                릴레이 모듈              솔레노이드 도어락
┌──────────┐                ┌──────────┐            ┌──────────┐
│ GPIO 17  │─── 신호선 ────│ IN1      │            │          │
│ 5V (Pin2)│─── VCC   ────│ VCC      │─── COM ───│ 솔레노이드│
│ GND(Pin6)│─── GND   ────│ GND      │─── NO  ───│ (12V)    │
│          │                │          │            │          │
│ GPIO 27  │─── LED 녹색                           └──────────┘
│ GPIO 22  │─── LED 적색                              │
│ GPIO 5   │─── 부저                                12V 전원
│          │                                         (+) ────┘
│ Camera   │─── CSI 케이블 ─── Pi Camera             (-) ────┘
└──────────┘
```

### 설치

```bash
# Raspbian에서
sudo apt update
sudo apt install libzbar0 libzbar-dev python3-opencv
pip3 install requests pyzbar opencv-python picamera RPi.GPIO

# 실행
cd ~/study_cafe/hardware/raspberry_pi
python3 door_controller.py --server http://서버IP:5000
```

### 부팅 시 자동 실행

```bash
# /etc/rc.local 또는 systemd 서비스 등록
sudo nano /etc/systemd/system/study-cafe-door.service
```

```ini
[Unit]
Description=Study Cafe Door Controller
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/pi/study_cafe/hardware/raspberry_pi/door_controller.py --server http://서버IP:5000
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable study-cafe-door
sudo systemctl start study-cafe-door
```

---

## 방식 B: ESP32 + 전용 QR 스캐너 모듈 (소형/저비용)

### 필요 부품

| 부품 | 설명 | 예상 가격 |
|------|------|-----------|
| ESP32 개발보드 | WiFi 내장 컨트롤러 | 8천 원 |
| GM-65S QR 스캐너 | 전용 QR 인식 모듈 | 2~3만 원 |
| 릴레이 모듈 | 도어락 제어 | 2천 원 |
| 12V 솔레노이드 도어락 | 물리적 잠금/해제 | 1~2만 원 |
| 12V 전원 어댑터 | 도어락용 | 5천 원 |
| (선택) OLED 0.96" | 상태 표시 | 3천 원 |
| **합계** | | **약 4~6만 원** |

### 배선도

```
ESP32               QR 스캐너 (GM-65S)         릴레이           도어락
┌──────────┐        ┌──────────┐              ┌──────────┐    ┌──────────┐
│ GPIO16   │───RX──│ TX       │              │ IN1      │    │          │
│ GPIO17   │───TX──│ RX       │              │ VCC(5V)  │    │ 솔레노이드│
│ 3.3V     │───VCC─│ VCC      │   GPIO25 ───│ IN1      │───│ (12V)    │
│ GND      │───GND─│ GND      │   5V     ───│ VCC      │    │          │
│          │        └──────────┘   GND    ───│ GND      │───│          │
│ GPIO25   │─── 릴레이                        └──────────┘    └──────────┘
│ GPIO26   │─── LED 녹색
│ GPIO27   │─── LED 적색
│ GPIO14   │─── 부저
│ GPIO21   │─── OLED SDA (선택)
│ GPIO22   │─── OLED SCL (선택)
└──────────┘
```

### 설치

1. Arduino IDE에 ESP32 보드 매니저 설치
2. 라이브러리 설치: ArduinoJson (Benoit Blanchon)
3. `door_controller_esp32.ino` 열기
4. WiFi SSID/비밀번호, 서버 주소 수정
5. ESP32에 업로드
6. 시리얼 모니터(115200 baud)로 상태 확인

---

## 방식 C: 상용 QR 스캐너 + 릴레이 (가장 간단)

### 필요 부품

| 부품 | 설명 | 예상 가격 |
|------|------|-----------|
| 상용 테이블형 QR 스캐너 | USB/시리얼 출력 | 3~5만 원 |
| Raspberry Pi Zero 2 W | 스캐너 데이터 처리 | 2만 원 |
| 릴레이 모듈 + 도어락 | 동일 | 1.5만 원 |
| **합계** | | **약 6~8만 원** |

상용 QR 스캐너는 USB 키보드처럼 동작하므로, 스캔된 데이터가 직접 시리얼 입력으로 들어옵니다. 별도 QR 인식 소프트웨어 불필요.

---

## 서버 API (하드웨어용)

### POST /api/door/verify
토큰 검증만 수행 (문 개폐하지 않음)

```json
// 요청
{"token": "a4f714f74f0d..."}

// 응답 (입실 가능)
{"success": true, "action": "checkin_ready", "seat_number": "A1", "username": "hong", "message": "입실 가능 — A1 좌석"}

// 응답 (출실 가능)
{"success": true, "action": "checkout_ready", "seat_number": "A1", "username": "hong", "message": "퇴실 가능 — A1 좌석"}

// 응답 (실패)
{"success": false, "error": "QR 코드가 만료되었습니다."}
```

### POST /api/door/checkin
입실 처리 + 도어락 해제 신호

```json
// 요청
{"token": "a4f714f74f0d..."}

// 응답 (성공)
{"success": true, "action": "checkin", "seat_number": "A1", "username": "hong", "remaining_seconds": 14399, "message": "입실 완료 — A1 좌석 (이용시간 240분)"}
```

### POST /api/door/checkout
출실 처리 + 도어락 해제 신호

```json
// 요청
{"token": "a4f714f74f0d..."}

// 응답 (성공)
{"success": true, "action": "checkout", "seat_number": "A1", "username": "hong", "message": "출실 완료 — A1 좌석"}
```

---

## 도어락 선택 가이드

### 전자식 솔레노이드 도어락 (권장)
- 릴레이 ON → 솔레노이드 당김 → 문 열림
- 릴레이 OFF → 스프링으로 자동 잠금
- 12V 전원 필요
- 설치 간단, 저렴

### 전자석 도어락 (매그네틱 락)
- 릴레이 OFF → 전자석 해제 → 문 열림 (반전 논리)
- 문이 닫혀 있을 때 전자석으로 밀착
- 상시 잠금 방식 (정전 시 열림 주의)

### 기존 도어락 연동
- 기존 도어락의 리모컨/버튼 단자에 릴레이 병렬 연결
- 릴레이 ON = 버튼 누름 효과

---

## 보안 주의사항

1. **API 인증 추가**: 현재 하드웨어 API에 인증이 없음. 프로덕션에서는 API 키 또는 토큰 인증 필요
2. **HTTPS 사용**: 네트워크 스니핑 방지
3. **토큰 만료**: QR 토큰은 1회성이며 만료 시간이 있음 (2시간/4시간)
4. **물리적 보안**: 컨트롤러와 릴레이는 조작 불가능한 위치에 설치
5. **비상시 수동 개폐**: 비상 버튼 또는 수동 키 병행 필요