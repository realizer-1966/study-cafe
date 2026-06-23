"""
Study Cafe Door Controller — Raspberry Pi
QR 코드를 카메라로 인식 → 서버 API 호출 → 릴레이 제어로 도어락 개폐

하드웨어 연결:
  - Pi Camera V2 또는 USB 웹캠
  - 릴레이 모듈 IN1 → GPIO 17
  - (선택) LED: GPIO 27 (녹색=성공), GPIO 22 (적색=실패)
  - (선택) 부저: GPIO 5

설치 (Raspberry Pi):
  sudo apt install libzbar0 libzbar-dev
  pip install requests pyzbar opencv-python picamera RPi.GPIO

실행:
  python3 door_controller.py --server http://서버IP:5000
"""

import sys
import time
import argparse
import threading
import requests

# --- QR 인식 라이브러리 ---
try:
    import cv2
    from pyzbar.pyzbar import decode, ZBarSymbol
except ImportError:
    print("ERROR: cv2, pyzbar 설치 필요")
    print("  sudo apt install libzbar0 libzbar-dev")
    print("  pip install opencv-python pyzbar")
    sys.exit(1)

# --- GPIO (Raspberry Pi 전용, PC에서는 테스트 모드로 동작) ---
try:
    import RPi.GPIO as GPIO
    ON_PI = True
except (ImportError, RuntimeError):
    ON_PI = False
    print("WARNING: RPi.GPIO를 사용할 수 없습니다. 테스트 모드로 동작합니다.")


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
RELAY_PIN = 17        # 릴레이 IN1
LED_GREEN = 27        # 성공 LED
LED_RED = 22          # 실패 LED
BUZZER_PIN = 5        # 부저

DOOR_OPEN_SECONDS = 3  # 문 열림 유지 시간 (초)
CAMERA_INDEX = 0       # 카메라 번호 (0=기본, 1=USB 웹캠)
COOLDOWN_SECONDS = 5   # 같은 QR 재스캔 방지 (초)


# ---------------------------------------------------------------------------
# GPIO 초기화
# ---------------------------------------------------------------------------
def setup_gpio():
    if not ON_PI:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [RELAY_PIN, LED_GREEN, LED_RED, BUZZER_PIN]:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    print(f"GPIO 초기화 완료 (릴레이={RELAY_PIN}, 녹색={LED_GREEN}, 적색={LED_RED})")


def door_open():
    """릴레이 ON → 도어락 해제 → DOOR_OPEN_SECONDS 후 자동 잠금."""
    if ON_PI:
        GPIO.output(RELAY_PIN, GPIO.HIGH)
        GPIO.output(LED_GREEN, GPIO.HIGH)
    print(f"🚪 문 열림 ({DOOR_OPEN_SECONDS}초 후 자동 닫힘)")
    time.sleep(DOOR_OPEN_SECONDS)
    if ON_PI:
        GPIO.output(RELAY_PIN, GPIO.LOW)
        GPIO.output(LED_GREEN, GPIO.LOW)
    print("🔒 문 닫힘")


def signal_success():
    """성공 신호 (녹색 LED + 부저)."""
    if ON_PI:
        GPIO.output(LED_GREEN, GPIO.HIGH)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(0.3)
        GPIO.output(LED_GREEN, GPIO.LOW)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
    else:
        print("✅ 성공 신호")


def signal_error():
    """실패 신호 (적색 LED + 부저 2회)."""
    if ON_PI:
        for _ in range(2):
            GPIO.output(LED_RED, GPIO.HIGH)
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(0.2)
            GPIO.output(LED_RED, GPIO.LOW)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.15)
    else:
        print("❌ 실패 신호")


# ---------------------------------------------------------------------------
# 서버 API 호출
# ---------------------------------------------------------------------------
def call_door_api(server_url, token, action):
    """
    action: 'checkin' 또는 'checkout'
    서버의 /api/door/<action> 엔드포인트 호출.
    """
    url = f"{server_url}/api/door/{action}"
    payload = {"token": token}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "서버에 연결할 수 없습니다."}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "서버 응답 시간 초과."}
    except Exception as e:
        return {"success": False, "error": f"API 오류: {e}"}


def verify_token(server_url, token):
    """토큰 상태만 확인 (문 개폐하지 않음). action 결정용."""
    url = f"{server_url}/api/door/verify"
    payload = {"token": token}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# QR 인식 메인 루프
# ---------------------------------------------------------------------------
def extract_token_from_qr(qr_data: str) -> str:
    """QR 데이터에서 토큰 추출.
    QR 형식: http://서버/qr/scan?token=xxx
    또는 단순 토큰 문자열.
    """
    if "token=" in qr_data:
        return qr_data.split("token=")[-1].split("&")[0].strip()
    return qr_data.strip()


def main():
    parser = argparse.ArgumentParser(description="Study Cafe Door Controller")
    parser.add_argument("--server", required=True,
                        help="서버 URL (예: http://192.168.0.10:5000)")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX,
                        help=f"카메라 번호 (기본: {CAMERA_INDEX})")
    args = parser.parse_args()

    server_url = args.server.rstrip("/")
    print(f"\n{'='*50}")
    print(f"  Study Cafe Door Controller")
    print(f"  서버: {server_url}")
    print(f"  카메라: {args.camera}")
    print(f"  GPIO: {'활성' if ON_PI else '테스트 모드'}")
    print(f"{'='*50}\n")

    setup_gpio()

    # 카메라 초기화
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"ERROR: 카메라 {args.camera}을 열 수 없습니다.")
        sys.exit(1)

    print("카메라 준비 완료. QR 코드를 스캔하세요... (Ctrl+C 종료)\n")

    last_token = None
    last_scan_time = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("WARNING: 프레임을 읽을 수 없습니다.")
                time.sleep(0.5)
                continue

            # QR 코드 인식
            decoded_objects = decode(frame, symbols=[ZBarSymbol.QRCODE])

            for obj in decoded_objects:
                qr_data = obj.data.decode("utf-8")
                token = extract_token_from_qr(qr_data)
                now = time.time()

                # 같은 QR 코드 재스캔 방지 (쿨다운)
                if token == last_token and (now - last_scan_time) < COOLDOWN_SECONDS:
                    continue

                last_token = token
                last_scan_time = now
                print(f"\n📷 QR 인식: {token[:20]}...")

                # 1단계: 토큰 검증 → 입실인지 출실인지 판단
                verify_result = verify_token(server_url, token)
                if verify_result is None:
                    print("  ⚠️ 서버 연결 실패")
                    signal_error()
                    continue

                if not verify_result.get("success"):
                    print(f"  ❌ {verify_result.get('error', '알 수 없는 오류')}")
                    signal_error()
                    continue

                action = "checkin" if verify_result.get("action") == "checkin_ready" else "checkout"
                action_label = "입실" if action == "checkin" else "출실"
                print(f"  → {action_label} 처리 중...")

                # 2단계: 실제 입실/출실 API 호출
                result = call_door_api(server_url, token, action)
                print(f"  응답: {result}")

                if result.get("success"):
                    print(f"  ✅ {result.get('message', '성공')}")
                    signal_success()

                    # 3단계: 도어락 해제 (별도 스레드로 비동기 처리)
                    door_thread = threading.Thread(target=door_open, daemon=True)
                    door_thread.start()
                else:
                    print(f"  ❌ {result.get('error', '실패')}")
                    signal_error()

                # 카메라 피드 표시 (선택)
                # cv2.putText(frame, result.get('message', ''), (10, 30),
                #             cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # 카메라 화면 표시 (주석 해제하면 미리보기 창이 열림)
            # cv2.imshow("QR Scanner", frame)
            # if cv2.waitKey(1) & 0xFF == ord('q'):
            #     break

            time.sleep(0.1)  # CPU 절약

    except KeyboardInterrupt:
        print("\n\n종료 중...")
    finally:
        cap.release()
        # cv2.destroyAllWindows()
        if ON_PI:
            GPIO.cleanup()
        print("종료 완료.")


if __name__ == "__main__":
    main()