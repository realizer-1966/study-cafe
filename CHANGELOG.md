# 스터디 카페 웹 앱 - 변경 이력 정리 문서

## 프로젝트 개요

- 프로젝트명: Study Cafe Web App
- 기술 스택: Flask (Python) + SQLite + HTML/CSS/JS
- 저장소: https://github.com/realizer-1966/study-cafe
- 실행 환경: Termux/Android (개발), Raspberry Pi (운영 권장)
- 서버 주소: http://127.0.0.1:5000
- 전체 코드: 약 3,275줄 (app.py 1,284줄, 템플릿 1,529줄, CSS 293줄, 하드웨어 169줄)

---

## 커밋 히스토리 (7개)

| # | 커밋 | 날짜 | 내용 |
|---|------|------|------|
| 1 | c13b1a7 | 2026-06-24 | 초기 커밋: 스터디 카페 웹 앱 (QR 입실/퇴실) |
| 2 | 27bc192 | 2026-06-24 | 하드웨어 도어 컨트롤러 + JSON API 추가 |
| 3 | fea7229 | 2026-06-25 | 휴대폰 QR 스캐너 페이지 (/scanner) 추가 |
| 4 | e81b52e | 2026-06-25 | QR 스캐너 전면/후면 카메라 전환 버튼 |
| 5 | 58ac473 | 2026-06-25 | WiFi 스마트 릴레이 지원 (Shelly/Sonoff) |
| 6 | adbad29 | 2026-06-27 | 세션 시간 연장 기능 + 라즈베리파이 ngrok 가이드 |
| 7 | 3a18c84 | 2026-06-27 | 회원별 다중 좌석 예약 허용 |

---

## 커밋별 상세 변경 내용

### 1. c13b1a7 - 초기 커밋 (2026-06-24)

**추가된 기능:**
- 회원가입 / 로그인 / 로그아웃 (세션 기반 인증)
- 좌석 맵 페이지 (A/B/C/D zone, 20석)
- 좌석 예약 시스템
- QR 코드 생성 (예약 토큰 기반)
- QR 스캔 페이지 (/qr/scan) - 입실/퇴실 처리
- 이용권 관리 (1일권 / 7일권 / 30일권)
- 결제 내역 조회
- 관리자 대시보드 (좌석 현황, 결제 내역, 예약 현황)
- 실시간 카운트다운 타이머
- 자동 만료 처리 (예약 QR 2시간, 세션 4시간)

**주요 파일:**
- app.py (Flask 앱)
- templates/ (base, index, login, register, seats, my_qr, qr_scan, plans, payments, admin, manage_seats)
- static/css/style.css

**설정값:**
- QR_EXPIRE_MINUTES = 120 (예약 후 체크인 대기 2시간)
- SESSION_EXPIRE_MINUTES = 240 (입실 후 이용 시간 4시간)

---

### 2. 27bc192 - 하드웨어 도어 컨트롤러 + JSON API (2026-06-24)

**추가된 기능:**
- Raspberry Pi GPIO 릴레이 제어 (door_controller.py)
- ESP32 도어 컨트롤러 펌웨어 (door_controller_esp32.ino)
- JSON API 엔드포인트:
  - POST /api/door/verify - QR 토큰 검증
  - POST /api/door/checkin - 입실 처리
  - POST /api/door/checkout - 퇴실 처리
  - GET /api/seats - 전체 좌석 현황
  - GET /api/my-reservation - 내 예약 정보
- 입실/퇴실 시 자동 도어락 제어 (릴레이 ON/OFF)

**하드웨어 구성:**
- Raspberry Pi: GPIO 17번 핀 -> 릴레이 모듈 -> 도어락
- ESP32: WiFi 기반 HTTP API로 릴레이 제어
- 하드웨어 없이도 소프트웨어 전용으로 동작 가능

---

### 3. fea7229 - 휴대폰 QR 스캐너 페이지 (2026-06-25)

**추가된 기능:**
- /scanner 페이지 - 브라우저 기반 QR 스캐너
- jsQR 라이브러리 사용 (앱 설치 불필요)
- 실시간 카메라 스캔 + 스캔 프레임 오버레이
- QR 인식 -> 자동 verify -> 자동 입실/퇴실 처리
- 성공/실패 결과를 색상 카드로 표시 (녹색=성공, 적색=실패)
- 입실 시 남은 시간 실시간 카운트다운
- 같은 QR 3초 내 재스캔 방지 (쿨다운)
- 최근 5건 스캔 기록 표시
- 스마트폰 브라우저만 있으면 됨 (HTTPS 필요 - 카메라 접근)
- 중고 폰을 출입문 스캐너로 재활용 가능

**테스트 결과 (6/6 PASS):**
- verify, checkin, verify-after, checkout, invalid, completed

---

### 4. e81b52e - 전면/후면 카메라 전환 (2026-06-25)

**추가된 기능:**
- /scanner 페이지에 전면/후면 카메라 전환 버튼 추가
- 카메라 facingMode 전환 (user/environment)
- 스캔 방향에 맞춰 카메라 선택 가능

---

### 5. 58ac473 - WiFi 스마트 릴레이 지원 (2026-06-25)

**추가된 기능:**
- WiFi 스마트 릴레이 지원 (Shelly / Sonoff / Generic HTTP)
- 관리자 페이지에서 릴레이 설정:
  - GET /api/relay/config - 릴레이 설정 조회
  - POST /api/relay/config - 릴레이 설정 변경
  - POST /api/relay/test - 릴레이 테스트
- 입실/퇴실 시 자동으로 릴레이 HTTP 호출
- RELAY_TIMEOUT = 5초 (HTTP 요청 타임아웃)
- 하드웨어 없이도 릴레이 비활성화 상태로 운영 가능

**지원 기기:**
- Shelly: http://<IP>/relay/0?turn=on|off
- Sonoff: http://<IP>/cm?cmnd=Power%20On|Off
- Generic: 커스텀 ON/OFF URL 지원

---

### 6. adbad29 - 세션 시간 연장 + ngrok 가이드 (2026-06-27)

**추가된 기능:**
- 세션 시간 연장 시스템
  - /seats/extend/<res_id> 라우트 (POST)
  - 입실 중일 때 60분 연장, 최대 2회
  - reservations 테이블에 extensions_count 컬럼 추가 (자동 마이그레이션)
  - 내 QR 페이지에서 연장 버튼 표시 (입실 중 + 남은 연장 횟수 > 0)
  - 연장 횟수 초과 시 버튼 자동 숨김 + 안내 메시지
  - 확인 다이얼로그로 실수 방지

**설정값:**
- EXTEND_MINUTES = 60 (1회 연장 시간)
- MAX_EXTENSIONS = 2 (최대 연장 횟수)

**추가된 문서:**
- RASPBERRY_PI_NGROK_GUIDE.md
  - 라즈베리파이 환경 설정 (저장소 클론, 의존성, 서버 실행)
  - ngrok 설치 및 실행 (snap/직접 다운로드, 토큰 인증)
  - 접속 주소 표 (메인, 로그인, 좌석, QR, 스캐너, 관리자)
  - 보안 주의사항 (admin 비밀번호, SECRET_KEY, API 인증)
  - ngrok 무료 플랜 제한 (URL 변경, 동시 연결)
  - 데이터베이스 분리 안내 (Termux vs RPi)
  - systemd 자동 실행 설정

---

### 7. 3a18c84 - 다중 좌석 예약 허용 (2026-06-27)

**변경 내용:**
- 한 회원이 여러 좌석을 동시에 예약할 수 있도록 변경

**app.py 변경:**
- seat_map(): 단일 예약 조회(LIMIT 1) -> 다중 예약 조회(fetchall)
- reserve_seat(): 기존 예약 중복 방지 로직 제거
- my_qr(): 단일 reservation -> cards 리스트 (예약별 개별 QR 카드)

**templates/seats.html 변경:**
- my_res_info 루프로 다중 예약 표시
- 예약별 개별 카운트다운 타이머 ID (seats-countdown-<res_id>)
- 예약별 개별 취소/퇴실 버튼
- 예약 건수 표시 ("내 예약 현황 (N건)")
- 예약 버튼: my_res 체크 제거 (항상 표시)

**templates/my_qr.html 변경:**
- cards 리스트 루프로 다중 QR 카드 렌더링
- 예약별 개별 QR 코드, 타이머, 연장 버튼, 취소 버튼
- 예약 없을 때 안내 메시지 + 좌석 예약 링크
- 이용 방법에 다중 좌석 예약 안내 추가

**테스트 결과 (16단계 PASS):**
- 회원가입 -> 로그인 -> 이용권 구매
- 좌석 3개 동시 예약 (A1, A2, A3)
- 좌석 페이지에 3개 예약 표시
- 내 QR 페이지에 QR 3개 표시
- 2개 좌석 입실 (checkin)
- 입실중 2 + 예약 1 혼재 상태 표시
- 입실 중인 2좌석에 연장 버튼 각각 표시
- 1차 연장 동작
- 2개 좌석 퇴실
- 3번째 좌석 예약 취소
- 최종 예약 0건 확인

---

## 전체 라우트 목록 (30개)

### 사용자 페이지
| 라우트 | 메서드 | 기능 |
|--------|--------|------|
| / | GET | 메인 페이지 |
| /register | GET/POST | 회원가입 |
| /login | GET/POST | 로그인 |
| /logout | GET | 로그아웃 |
| /seats | GET | 좌석 맵 (다중 예약 현황) |
| /seats/reserve/<id> | POST | 좌석 예약 |
| /seats/cancel/<id> | POST | 예약 취소 |
| /seats/release/<id> | POST | 퇴실 |
| /seats/extend/<id> | POST | 시간 연장 (60분, 최대 2회) |
| /my-qr | GET | 내 QR 코드 (다중 카드) |
| /qr/<token>.png | GET | QR 코드 이미지 |
| /qr/scan | GET | QR 스캔 페이지 |
| /qr/checkin | POST | QR 입실 처리 |
| /qr/checkout | POST | QR 퇴실 처리 |
| /plans | GET | 이용권 목록 |
| /plans/purchase/<id> | POST | 이용권 구매 |
| /payments | GET | 결제 내역 |
| /scanner | GET | 휴대폰 QR 스캐너 |

### 관리자
| 라우트 | 메서드 | 기능 |
|--------|--------|------|
| /admin | GET | 관리자 대시보드 |
| /admin/seats/manage | GET | 좌석 관리 |
| /admin/seats/add | POST | 좌석 추가 |
| /admin/seats/delete/<id> | POST | 좌석 삭제 |

### API
| 라우트 | 메서드 | 기능 |
|--------|--------|------|
| /api/seats | GET | 전체 좌석 현황 JSON |
| /api/my-reservation | GET | 내 예약 정보 JSON |
| /api/door/verify | POST | QR 토큰 검증 |
| /api/door/checkin | POST | 입실 처리 + 릴레이 제어 |
| /api/door/checkout | POST | 퇴실 처리 + 릴레이 제어 |
| /api/relay/config | GET | 릴레이 설정 조회 |
| /api/relay/config | POST | 릴레이 설정 변경 |
| /api/relay/test | POST | 릴레이 테스트 |

---

## 파일 구조

```
study-cafe/
├── app.py                          # Flask 메인 앱 (1,284줄)
├── study_cafe.db                    # SQLite 데이터베이스
├── README.md                       # 프로젝트 README
├── RASPBERRY_PI_NGROK_GUIDE.md     # 라즈베리파이 + ngrok 가이드
├── CHANGELOG.md                    # 이 변경 이력 문서
├── .gitignore
├── static/
│   └── css/
│       └── style.css               # 공통 스타일 (293줄)
├── templates/
│   ├── base.html                   # 베이스 템플릿
│   ├── index.html                  # 메인 페이지
│   ├── login.html                  # 로그인
│   ├── register.html               # 회원가입
│   ├── seats.html                  # 좌석 맵 + 다중 예약 현황
│   ├── my_qr.html                  # 내 QR 코드 (다중 카드)
│   ├── qr_scan.html                # QR 스캔 페이지 (웹용)
│   ├── scanner.html                # 휴대폰 QR 스캐너 (jsQR)
│   ├── plans.html                  # 이용권
│   ├── payments.html               # 결제 내역
│   ├── admin.html                  # 관리자 대시보드
│   └── manage_seats.html           # 좌석 관리
└── hardware/
    ├── README.md
    ├── raspberry_pi/
    │   └── door_controller.py      # RPi GPIO 릴레이 제어
    └── esp32/
        └── door_controller_esp32.ino  # ESP32 펌웨어
```

---

## 주요 설정값

| 설정 | 값 | 설명 |
|------|-----|------|
| QR_EXPIRE_MINUTES | 120 | 예약 후 체크인 대기 시간 (2시간) |
| SESSION_EXPIRE_MINUTES | 240 | 입실 후 이용 시간 (4시간) |
| EXTEND_MINUTES | 60 | 1회 연장 시간 (1시간) |
| MAX_EXTENSIONS | 2 | 최대 연장 횟수 |
| RELAY_TIMEOUT | 5 | 릴레이 HTTP 요청 타임아웃 (초) |
| 좌석 수 | 20 | A/B/C/D zone (각 5석) |

---

## 데이터베이스 스키마

### users
- id, username, email, password_hash, is_admin, created_at

### seats
- id, seat_number, zone, is_occupied, current_user_id, occupied_since

### reservations
- id, user_id, seat_id, start_time, qr_token, status, qr_expires_at, session_expires_at, check_in_time, check_out_time, extensions_count, created_at
- status: reserved / checked_in / completed / cancelled

### plans
- id, name, duration_days, price, description

### payments
- id, user_id, plan_id, amount, status, created_at

---

## 운영 환경

### 개발 (현재)
- Termux / Android
- python3 app.py (포트 5000)
- SQLite 로컬 파일 (study_cafe.db)

### 운영 (권장)
- Raspberry Pi + ngrok
- RASPBERRY_PI_NGROK_GUIDE.md 참조
- systemd 자동 실행 설정
- ngrok HTTPS (카메라 접근 필요)

---

## 추후 개선 방향

1. 보안: admin 비밀번호 변경, SECRET_KEY 환경변수화, API 인증 키 추가
2. 고정 URL: ngrok 유료 플랜 또는 Cloudflare Tunnel
3. 알림: 세션 만료 10분 전 푸시/SMS 알림
4. 통계: 일/주/월 단위 이용 통계, 좌석별 사용률
5. 예약 시스템: 시간대 사전 예약, 정기 예약
6. 결제 연동: 실제 결제 게이트웨이 연동 (토스, 카카오페이 등)