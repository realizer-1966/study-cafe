# Study Cafe Web App

스터디 카페 운영을 위한 웹 애플리케이션 (Flask + SQLite)

## 주요 기능

- **회원 관리**: 회원가입, 로그인, 로그아웃
- **좌석 예약**: zone별 좌석 배치도 (일반/프리미엄/그룹), 실시간 예약
- **QR 코드 입출입**: 예약 시 QR 토큰 발급, QR 스캔으로 입실/출실
- **만료 시간 관리**: 체크인 대기 2시간, 이용 시간 4시간, 자동 만료 처리
- **실시간 카운트다운**: 모든 페이지에서 남은 시간 표시 (JavaScript)
- **이용권 관리**: 1일권/7일권/30일권 구매
- **결제 내역**: 이용권 구매 내역 조회
- **관리자 대시보드**: 회원 수, 좌석 현황, 매출 통계, 예약 현황 (QR 입출입 상태 포함)

## 기술 스택

- Python 3.13 + Flask
- SQLite (내장 DB)
- Jinja2 템플릿 엔진
- qrcode 라이브러리 (QR 코드 생성)
- 반응형 CSS (모바일/PC 지원)

## 설치 및 실행

```bash
# 의존성 설치
pip install flask qrcode Pillow

# 서버 실행
python app.py

# 접속
# http://127.0.0.1:5000
# 관리자 계정: admin / admin123
```

## QR 입출입 플로우

1. 좌석 예약 → QR 토큰 + 만료 시간 자동 발급 (체크인 대기 2시간)
2. 내 QR 페이지에서 QR 코드 이미지 확인
3. 입구에서 QR 스캔 → /qr/scan 페이지 → 입실 버튼
4. 입실 시 이용 시간 4시간 자동 설정
5. 남은 시간 실시간 카운트다운 표시 (5분 이하 빨간색 경고)
6. 시간 만료 시 자동 퇴실 처리
7. 퇴실 시 QR 다시 스캔 → 출실 버튼

## 시간 설정

`app.py` 상단에서 조정 가능:

```python
QR_EXPIRE_MINUTES = 120       # 체크인 대기 시간 (분)
SESSION_EXPIRE_MINUTES = 240  # 이용 시간 (분)
```

## API

### 프론트엔드용
- `GET /api/seats` - 전체 좌석 현황 JSON
- `GET /api/my-reservation` - 내 예약 남은 시간 JSON

### 하드웨어용 (출입문 QR 스캐너)
- `POST /api/door/verify` - QR 토큰 검증 (입실/출실 판단)
- `POST /api/door/checkin` - 입실 처리 (JSON 반환)
- `POST /api/door/checkout` - 출실 처리 (JSON 반환)

자세한 내용은 [hardware/README.md](hardware/README.md) 참조

## 프로젝트 구조

```
study_cafe/
├── app.py                 # Flask 백엔드 (모든 라우트, DB, QR, 하드웨어 API)
├── static/
│   └── css/
│       └── style.css      # 반응형 스타일시트
├── templates/
│   ├── base.html           # 공통 레이아웃 (네비게이션)
│   ├── index.html          # 홈 (현황 대시보드)
│   ├── register.html       # 회원가입
│   ├── login.html          # 로그인
│   ├── seats.html          # 좌석 배치도 + 내 예약
│   ├── my_qr.html          # 내 QR 코드 (카운트다운)
│   ├── qr_scan.html        # QR 스캔 페이지 (입실/출실)
│   ├── plans.html          # 이용권 구매
│   ├── payments.html       # 결제 내역
│   ├── admin.html          # 관리자 대시보드
│   └── manage_seats.html   # 좌석 관리 (추가/삭제)
└── hardware/               # 출입문 QR 스캐너 장치
    ├── README.md            # 제작 가이드 (부품, 배선, 설치)
    ├── raspberry_pi/
    │   └── door_controller.py   # RPi 컨트롤러 (카메라 QR 인식 + 릴레이)
    └── esp32/
        └── door_controller_esp32.ino  # ESP32 컨트롤러 (QR 모듈 + 릴레이)
```