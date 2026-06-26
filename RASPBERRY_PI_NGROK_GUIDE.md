# 라즈베리파이 + ngrok 외부 서비스 가이드

## 구성도

```
스마트폰(외부) → ngrok URL (HTTPS) → 라즈베리파이(Flask:5000) → SQLite DB
```

GitHub 저장소: https://github.com/realizer-1966/study-cafe

---

## 1. 라즈베리파이 환경 설정

### 저장소 클론

```bash
git clone https://github.com/realizer-1966/study-cafe.git
cd study-cafe
```

### 의존성 설치

```bash
sudo apt update
sudo apt install python3-pip
pip3 install flask qrcode requests
```

### 서버 실행

```bash
python3 app.py
```

서버는 0.0.0.0:5000 에서 실행됨

---

## 2. ngrok 설치 및 실행

### ngrok 설치

방법 A - snap 설치:

```bash
sudo snap install ngrok
```

방법 B - 직접 다운로드 (arm64):

```bash
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar xzf ngrok-v3-stable-linux-arm64.tgz
sudo mv ngrok /usr/local/bin/
```

### 토큰 인증

1. https://ngrok.com 에서 가입 후 토큰 발급
2. 토큰 등록:

```bash
ngrok config add-authtoken YOUR_TOKEN
```

### 외부 노출 실행

```bash
ngrok http 5000
```

실행 후 터미널에 표시되는 URL(예: https://xxxx.ngrok-free.app)이 외부 접속 주소.

---

## 3. 접속 주소

| 페이지 | URL |
|--------|-----|
| 메인 | https://xxxx.ngrok-free.app/ |
| 로그인 | https://xxxx.ngrok-free.app/login |
| 좌석 예약 | https://xxxx.ngrok-free.app/seats |
| 내 QR | https://xxxx.ngrok-free.app/my-qr |
| QR 스캐너 | https://xxxx.ngrok-free.app/scanner |
| 관리자 | https://xxxx.ngrok-free.app/admin |

관리자 계정: admin / admin123

---

## 4. 주의사항

### 4.1 카메라 (QR 스캐너 /scanner)

- ngrok URL은 HTTPS가 자동 제공되므로 외부 스마트폰에서 카메라 접근 가능
- 즉, 외부 폰에서 QR 스캔 가능 (로컬 HTTP에서는 127.0.0.1만 카메라 작동)
- 전면/후면 카메라 전환 버튼 지원

### 4.2 보안

- 현재 admin 비밀번호가 admin123이므로 반드시 변경 필요
- SECRET_KEY를 환경변수로 설정 권장:

```bash
export SECRET_KEY="랜덤문자열"
python3 app.py
```

- API 인증이 없으므로 누구나 /api/door/* 호출 가능 — 나중에 API 키 추가 필요

### 4.3 ngrok 무료 플랜 제한

- URL이 ngrok 재시작할 때마다 변경됨 (고정 URL은 유료 플랜)
- 동시 연결 제한이 있으므로 다수 사용자 환경에서는 유료 플랜 권장
- 무료 플랜: 1개 터널, URL 변경 시마다 새 주소 발급

### 4.4 데이터베이스

- SQLite는 로컬 파일(study_cafe.db)이므로 라즈베리파이에 데이터가 저장됨
- Termux(현재 개발환경)와 라즈베리파이(운영서버)의 DB는 분리됨 — 데이터 공유 안 됨
- 라즈베리파이를 메인 서버로 쓰고 Termux는 개발/테스트용으로 분리 권장

---

## 5. 부팅 시 자동 실행 (선택)

### Flask 서버 자동 실행

```bash
sudo nano /etc/systemd/system/study-cafe.service
```

```ini
[Unit]
Description=Study Cafe Flask Server
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/pi/study-cafe/app.py
Restart=always
User=pi
WorkingDirectory=/home/pi/study-cafe
Environment=SECRET_KEY=여기에_랜덤문자열

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable study-cafe
sudo systemctl start study-cafe
```

### ngrok 자동 실행

```bash
sudo nano /etc/systemd/system/ngrok.service
```

```ini
[Unit]
Description=ngrok tunnel
After=network-online.target study-cafe.service

[Service]
Type=simple
ExecStart=/usr/local/bin/ngrok http 5000
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable ngrok
sudo systemctl start ngrok
```

---

## 6. 전체 동작 흐름

1. 사용자가 스마트폰에서 ngrok URL 접속
2. 회원가입/로그인
3. 좌석 예약 → QR 코드 발급
4. 출입문에서 /scanner 페이지 열고 QR 코드 스캔
5. 서버에서 토큰 검증 → 입실/출실 처리
6. WiFi 릴레이 활성화 시 자동으로 도어락 개방 (관리자 페이지에서 설정)
7. 관리자 페이지에서 좌석 현황, 결제 내역, 예약 현황 확인