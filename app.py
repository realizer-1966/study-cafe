"""
Study Cafe Web App with QR Check-in/Check-out + Expiry Timer
- 회원가입/로그인
- 좌석 예약 및 관리 (예약 시 QR 토큰 발급 + 만료 시간)
- QR 코드 입실/출실
- QR 만료 시간 체크 + 남은 시간 표시
- 결제 및 정기권 관리
- 관리자 대시보드
"""
import os
import uuid
import sqlite3
import io
import base64
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, g, flash, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "study-cafe-secret-key-2026")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "study_cafe.db")

# ---------------------------------------------------------------------------
# 시간 설정 (분 단위)
# ---------------------------------------------------------------------------
QR_EXPIRE_MINUTES = 120       # 예약 후 체크인 대기 시간 (2시간)
SESSION_EXPIRE_MINUTES = 240  # 입실 후 이용 시간 (4시간)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# WiFi 스마트 릴레이 제어 (Shelly / Sonoff)
# ---------------------------------------------------------------------------

logger = logging.getLogger("relay")
logger.setLevel(logging.INFO)

RELAY_TIMEOUT = 5  # HTTP 요청 타임아웃 (초)


def get_relay_config(db=None):
    """릴레이 설정을 DB에서 조회. db가 없으면 새 연결."""
    own_conn = db is None
    if own_conn:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM relay_config WHERE id=1").fetchone()
    if own_conn:
        db.close()
    return row


def trigger_relay(action="checkin"):
    """
    WiFi 스마트 릴레이를 제어하여 도어락을 열었다가 닫는다.
    Shelly: GET /relay/{channel}?turn=on  → wait → turn=off
    Sonoff: GET /relay/0?turn=on (web UI firmware, Tasmota) → wait → turn=off

    action: "checkin" | "checkout" | "test" (로깅 구분용)
    반환: (success: bool, message: str)
    """
    cfg = get_relay_config()
    if not cfg or not cfg["enabled"]:
        return False, "릴레이 비활성화됨"

    ip = cfg["ip_address"].strip()
    if not ip:
        return False, "릴레이 IP 주소가 설정되지 않음"

    port = cfg["port"] or 80
    device_type = cfg["device_type"] or "shelly"
    channel = cfg["relay_channel"] or 0
    duration_ms = cfg["open_duration_ms"] or 3000
    username = cfg["username"] or ""
    password = cfg["password"] or ""

    base_url = f"http://{ip}:{port}"
    auth = (username, password) if username else None
    duration_sec = max(0.5, duration_ms / 1000.0)

    try:
        if device_type == "shelly":
            # Shelly 1 / Shelly Plus 1
            # Gen1: /relay/0?turn=on
            # Gen2: /rpc/Switch.Set?id=0&on=true
            # Gen1 시도 → 실패 시 Gen2 시도
            on_url = f"{base_url}/relay/{channel}?turn=on"
            off_url = f"{base_url}/relay/{channel}?turn=off"

            # Gen1 시도
            resp = requests.get(on_url, auth=auth, timeout=RELAY_TIMEOUT)
            if resp.status_code == 404:
                # Gen2 (Plus) 시도
                on_url = f"{base_url}/rpc/Switch.Set?id={channel}&on=true"
                off_url = f"{base_url}/rpc/Switch.Set?id={channel}&on=false"
                resp = requests.get(on_url, auth=auth, timeout=RELAY_TIMEOUT)

            if resp.status_code != 200:
                return False, f"릴레이 ON 실패 (HTTP {resp.status_code})"

        elif device_type == "sonoff":
            # Sonoff Tasmota 펌웨어
            on_url = f"{base_url}/cm?cmnd=Power{channel+1}%20On"
            off_url = f"{base_url}/cm?cmnd=Power{channel+1}%20Off"
            resp = requests.get(on_url, auth=auth, timeout=RELAY_TIMEOUT)
            if resp.status_code != 200:
                return False, f"릴레이 ON 실패 (HTTP {resp.status_code})"

        elif device_type == "generic":
            # 범용: 단순 ON/OFF 엔드포인트
            on_url = f"{base_url}/relay/{channel}?turn=on"
            off_url = f"{base_url}/relay/{channel}?turn=off"
            resp = requests.get(on_url, auth=auth, timeout=RELAY_TIMEOUT)
            if resp.status_code != 200:
                return False, f"릴레이 ON 실패 (HTTP {resp.status_code})"

        else:
            return False, f"알 수 없는 릴레이 타입: {device_type}"

        # 열림 유지 후 자동 닫힘
        import time as _time
        _time.sleep(duration_sec)
        requests.get(off_url, auth=auth, timeout=RELAY_TIMEOUT)

        # 결과 기록
        now_str = fmt(datetime.now())
        result_msg = f"[{action}] 문 개방 {duration_sec:.1f}초 → 완료 ({ip}:{port})"
        db = sqlite3.connect(DB_PATH)
        db.execute(
            "UPDATE relay_config SET last_triggered_at=?, last_trigger_result=? WHERE id=1",
            (now_str, result_msg),
        )
        db.commit()
        db.close()

        logger.info("Relay triggered: %s", result_msg)
        return True, result_msg

    except requests.exceptions.Timeout:
        return False, f"릴레이 연결 시간 초과 ({ip}:{port})"
    except requests.exceptions.ConnectionError:
        return False, f"릴레이 연결 실패 — IP를 확인하세요 ({ip}:{port})"
    except Exception as e:
        return False, f"릴레이 오류: {e}"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seat_number TEXT UNIQUE NOT NULL,
            zone TEXT DEFAULT '일반',
            is_occupied INTEGER DEFAULT 0,
            current_user_id INTEGER,
            occupied_since TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            seat_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            check_in_time TEXT,
            check_out_time TEXT,
            qr_token TEXT UNIQUE,
            status TEXT DEFAULT 'reserved',
            qr_expires_at TEXT,
            session_expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (seat_id) REFERENCES seats(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            duration_days INTEGER NOT NULL,
            description TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            payment_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS relay_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 0,
            device_type TEXT DEFAULT 'shelly',
            ip_address TEXT DEFAULT '',
            port INTEGER DEFAULT 80,
            relay_channel INTEGER DEFAULT 0,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            open_duration_ms INTEGER DEFAULT 3000,
            last_triggered_at TEXT,
            last_trigger_result TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO relay_config (id, enabled) VALUES (1, 0)")
    c.execute("SELECT COUNT(*) FROM plans")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO plans (name, price, duration_days, description) VALUES (?,?,?,?)",
            [
                ("1일권", 5000, 1, "당일 이용 가능"),
                ("7일권", 30000, 7, "7일간 이용 가능"),
                ("30일권", 100000, 30, "30일간 이용 가능"),
            ],
        )
    c.execute("SELECT COUNT(*) FROM seats")
    if c.fetchone()[0] == 0:
        zones = [("A", "일반"), ("B", "일반"), ("C", "프리미엄"), ("D", "그룹")]
        for zone_letter, zone_name in zones:
            for i in range(1, 6):
                c.execute(
                    "INSERT INTO seats (seat_number, zone) VALUES (?, ?)",
                    (f"{zone_letter}{i}", zone_name),
                )
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO users (username, email, password, is_admin) VALUES (?,?,?,1)",
            ("admin", "admin@studycafe.com", generate_password_hash("admin123")),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 만료 시간 헬퍼
# ---------------------------------------------------------------------------
def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def calc_remaining_seconds(expires_at_str):
    """만료 시간까지 남은 초. 음수면 0."""
    if not expires_at_str:
        return None
    try:
        expires = parse(expires_at_str)
        diff = (expires - datetime.now()).total_seconds()
        return max(0, int(diff))
    except Exception:
        return None


def format_remaining(total_seconds):
    """초를 'X시간 Y분 Z초' 형식으로 변환."""
    if total_seconds is None:
        return "-"
    if total_seconds <= 0:
        return "만료됨"
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    if h > 0:
        return f"{h}시간 {m}분 {s}초"
    elif m > 0:
        return f"{m}분 {s}초"
    else:
        return f"{s}초"


def auto_expire_reservations(db):
    """만료된 예약/세션을 자동 처리."""
    now_str = fmt(datetime.now())
    # 예약 대기 만료 (reserved → expired)
    db.execute(
        """UPDATE reservations SET status='expired'
           WHERE status='reserved' AND qr_expires_at < ?""",
        (now_str,),
    )
    # 이용 시간 만료 (checked_in → session_expired + 좌석 해제)
    expired = db.execute(
        """SELECT id, seat_id FROM reservations
           WHERE status='checked_in' AND session_expires_at < ?""",
        (now_str,),
    ).fetchall()
    for r in expired:
        db.execute(
            "UPDATE reservations SET status='session_expired', check_out_time=? WHERE id=?",
            (now_str, r["id"]),
        )
        db.execute(
            "UPDATE seats SET is_occupied=0, current_user_id=NULL, occupied_since=NULL WHERE id=?",
            (r["seat_id"],),
        )
    db.commit()


# ---------------------------------------------------------------------------
# QR Code helpers
# ---------------------------------------------------------------------------
def generate_qr_token():
    return uuid.uuid4().hex


def make_qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=4,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def make_qr_base64(data: str) -> str:
    png_bytes = make_qr_png(data)
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            flash("관리자 권한이 필요합니다.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    auto_expire_reservations(db)
    seats = db.execute("SELECT * FROM seats ORDER BY seat_number").fetchall()
    total = len(seats)
    occupied = sum(1 for s in seats if s["is_occupied"])
    available = total - occupied
    return render_template("index.html", seats=seats, total=total,
                           occupied=occupied, available=available)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        phone = request.form.get("phone", "").strip()
        db = get_db()
        if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
            flash("이미 존재하는 아이디입니다.", "error")
            return redirect(url_for("register"))
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("이미 존재하는 이메일입니다.", "error")
            return redirect(url_for("register"))
        db.execute(
            "INSERT INTO users (username, email, password, phone) VALUES (?,?,?,?)",
            (username, email, generate_password_hash(password), phone),
        )
        db.commit()
        flash("회원가입 완료! 로그인해주세요.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = bool(user["is_admin"])
            flash(f"{user['username']}님 환영합니다!", "success")
            return redirect(url_for("index"))
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Routes — Seats & Reservations
# ---------------------------------------------------------------------------
@app.route("/seats")
@login_required
def seat_map():
    db = get_db()
    auto_expire_reservations(db)
    seats = db.execute("SELECT * FROM seats ORDER BY seat_number").fetchall()
    zones = {}
    for s in seats:
        zones.setdefault(s["zone"], []).append(s)
    my_res = db.execute(
        """SELECT r.*, s.seat_number, s.zone FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           WHERE r.user_id=? AND r.status IN ('reserved','checked_in')
           ORDER BY r.created_at DESC LIMIT 1""",
        (session["user_id"],),
    ).fetchone()
    # 남은 시간 계산
    remaining = None
    if my_res:
        if my_res["status"] == "reserved":
            remaining = calc_remaining_seconds(my_res["qr_expires_at"])
        elif my_res["status"] == "checked_in":
            remaining = calc_remaining_seconds(my_res["session_expires_at"])
    return render_template("seats.html", zones=zones, my_res=my_res,
                           remaining=remaining, format_remaining=format_remaining)


@app.route("/seats/reserve/<int:seat_id>", methods=["POST"])
@login_required
def reserve_seat(seat_id):
    db = get_db()
    auto_expire_reservations(db)
    seat = db.execute("SELECT * FROM seats WHERE id=?", (seat_id,)).fetchone()
    if not seat:
        flash("존재하지 않는 좌석입니다.", "error")
        return redirect(url_for("seat_map"))
    if seat["is_occupied"]:
        flash("이미 사용 중인 좌석입니다.", "error")
        return redirect(url_for("seat_map"))
    existing = db.execute(
        "SELECT * FROM reservations WHERE user_id=? AND status IN ('reserved','checked_in')",
        (session["user_id"],),
    ).fetchone()
    if existing:
        flash("이미 예약 중인 좌석이 있습니다. 먼저 취소하거나 퇴실해주세요.", "error")
        return redirect(url_for("seat_map"))

    now = datetime.now()
    qr_expires = now + timedelta(minutes=QR_EXPIRE_MINUTES)
    token = generate_qr_token()
    db.execute(
        """INSERT INTO reservations
           (user_id, seat_id, start_time, qr_token, status, qr_expires_at)
           VALUES (?,?,?,?,?,?)""",
        (session["user_id"], seat_id, fmt(now), token, "reserved", fmt(qr_expires)),
    )
    db.commit()
    flash(f"{seat['seat_number']}번 좌석 예약 완료! {QR_EXPIRE_MINUTES}분 내에 QR 코드로 입실해주세요.", "success")
    return redirect(url_for("my_qr"))


@app.route("/seats/cancel/<int:res_id>", methods=["POST"])
@login_required
def cancel_reservation(res_id):
    db = get_db()
    res = db.execute("SELECT * FROM reservations WHERE id=? AND user_id=?",
                     (res_id, session["user_id"])).fetchone()
    if not res:
        flash("예약을 찾을 수 없습니다.", "error")
        return redirect(url_for("seat_map"))
    if res["status"] == "checked_in":
        flash("이미 입실한 예약은 취소할 수 없습니다. 퇴실해주세요.", "error")
        return redirect(url_for("seat_map"))
    db.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (res_id,))
    db.commit()
    flash("예약이 취소되었습니다.", "success")
    return redirect(url_for("seat_map"))


@app.route("/seats/release/<int:seat_id>", methods=["POST"])
@login_required
def release_seat(seat_id):
    db = get_db()
    seat = db.execute("SELECT * FROM seats WHERE id=?", (seat_id,)).fetchone()
    if not seat:
        flash("존재하지 않는 좌석입니다.", "error")
        return redirect(url_for("seat_map"))
    if seat["current_user_id"] != session["user_id"] and not session.get("is_admin"):
        flash("본인 좌석만 퇴실할 수 있습니다.", "error")
        return redirect(url_for("seat_map"))
    now = fmt(datetime.now())
    db.execute(
        "UPDATE seats SET is_occupied=0, current_user_id=NULL, occupied_since=NULL WHERE id=?",
        (seat_id,),
    )
    db.execute(
        "UPDATE reservations SET check_out_time=?, status='completed' WHERE seat_id=? AND user_id=? AND status='checked_in'",
        (now, seat_id, session["user_id"]),
    )
    db.commit()
    flash(f"{seat['seat_number']}번 좌석 퇴실 처리되었습니다.", "success")
    return redirect(url_for("seat_map"))


# ---------------------------------------------------------------------------
# Routes — QR Code
# ---------------------------------------------------------------------------
@app.route("/my-qr")
@login_required
def my_qr():
    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        """SELECT r.*, s.seat_number, s.zone FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           WHERE r.user_id=? AND r.status IN ('reserved','checked_in')
           ORDER BY r.created_at DESC LIMIT 1""",
        (session["user_id"],),
    ).fetchone()
    if not res:
        flash("활성 예약이 없습니다. 먼저 좌석을 예약해주세요.", "error")
        return redirect(url_for("seat_map"))

    base_url = request.host_url.rstrip("/")
    qr_data = f"{base_url}/qr/scan?token={res['qr_token']}"
    qr_img = make_qr_base64(qr_data)

    # 남은 시간 계산
    if res["status"] == "reserved":
        remaining = calc_remaining_seconds(res["qr_expires_at"])
        remaining_label = "체크인 만료까지"
    else:
        remaining = calc_remaining_seconds(res["session_expires_at"])
        remaining_label = "이용 시간 종료까지"

    return render_template("my_qr.html", reservation=res, qr_img=qr_img,
                           checkin_url=qr_data, remaining=remaining,
                           remaining_label=remaining_label,
                           format_remaining=format_remaining)


@app.route("/qr/<qr_token>.png")
@login_required
def qr_image(qr_token):
    base_url = request.host_url.rstrip("/")
    qr_data = f"{base_url}/qr/scan?token={qr_token}"
    png = make_qr_png(qr_data)
    return Response(png, mimetype="image/png")


@app.route("/qr/scan")
def qr_scan():
    token = request.args.get("token", "").strip()
    if not token:
        return render_template("qr_scan.html", error="QR 토큰이 없습니다.")
    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        """SELECT r.*, s.seat_number, s.zone, u.username
           FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           JOIN users u ON r.user_id=u.id
           WHERE r.qr_token=?""",
        (token,),
    ).fetchone()
    if not res:
        return render_template("qr_scan.html", error="유효하지 않은 QR 코드입니다.")
    if res["status"] in ("cancelled", "completed"):
        return render_template("qr_scan.html", error="이 예약은 이미 종료되었습니다.",
                               reservation=res)
    if res["status"] == "expired":
        return render_template("qr_scan.html", error="QR 코드가 만료되었습니다. 다시 예약해주세요.",
                               reservation=res)
    if res["status"] == "session_expired":
        return render_template("qr_scan.html", error="이용 시간이 종료되었습니다.",
                               reservation=res)

    # 남은 시간
    if res["status"] == "reserved":
        remaining = calc_remaining_seconds(res["qr_expires_at"])
        remaining_label = "체크인 만료까지"
    else:
        remaining = calc_remaining_seconds(res["session_expires_at"])
        remaining_label = "이용 시간 종료까지"

    return render_template("qr_scan.html", reservation=res, token=token,
                           remaining=remaining, remaining_label=remaining_label,
                           format_remaining=format_remaining)


@app.route("/qr/checkin", methods=["POST"])
def qr_checkin():
    token = request.form.get("token", "").strip()
    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        "SELECT * FROM reservations WHERE qr_token=? AND status='reserved'",
        (token,),
    ).fetchone()
    if not res:
        flash("입실할 수 없습니다. 예약 상태를 확인해주세요.", "error")
        return redirect(url_for("qr_scan", token=token))
    # 만료 체크
    if res["qr_expires_at"]:
        remaining = calc_remaining_seconds(res["qr_expires_at"])
        if remaining is not None and remaining <= 0:
            db.execute("UPDATE reservations SET status='expired' WHERE id=?", (res["id"],))
            db.commit()
            flash("QR 코드가 만료되었습니다. 다시 예약해주세요.", "error")
            return redirect(url_for("qr_scan", token=token))

    seat = db.execute("SELECT * FROM seats WHERE id=?", (res["seat_id"],)).fetchone()
    if seat["is_occupied"]:
        flash("해당 좌석이 이미 사용 중입니다.", "error")
        return redirect(url_for("qr_scan", token=token))

    now = datetime.now()
    session_expires = now + timedelta(minutes=SESSION_EXPIRE_MINUTES)
    db.execute(
        """UPDATE reservations SET check_in_time=?, status='checked_in', session_expires_at=?
           WHERE id=?""",
        (fmt(now), fmt(session_expires), res["id"]),
    )
    db.execute(
        "UPDATE seats SET is_occupied=1, current_user_id=?, occupied_since=? WHERE id=?",
        (res["user_id"], fmt(now), res["seat_id"]),
    )
    db.commit()
    flash(f"입실 완료! 이용 시간은 {SESSION_EXPIRE_MINUTES}분입니다. 공부 화이팅! 📚", "success")
    return redirect(url_for("qr_scan", token=token))


@app.route("/qr/checkout", methods=["POST"])
def qr_checkout():
    token = request.form.get("token", "").strip()
    db = get_db()
    res = db.execute(
        "SELECT * FROM reservations WHERE qr_token=? AND status='checked_in'",
        (token,),
    ).fetchone()
    if not res:
        flash("출실할 수 없습니다. 먼저 입실해주세요.", "error")
        return redirect(url_for("qr_scan", token=token))
    now = fmt(datetime.now())
    db.execute(
        "UPDATE reservations SET check_out_time=?, status='completed' WHERE id=?",
        (now, res["id"]),
    )
    db.execute(
        "UPDATE seats SET is_occupied=0, current_user_id=NULL, occupied_since=NULL WHERE id=?",
        (res["seat_id"],),
    )
    db.commit()
    flash("출실 완료! 수고하셨습니다. 👋", "success")
    return redirect(url_for("qr_scan", token=token))


# ---------------------------------------------------------------------------
# Routes — Plans & Payment
# ---------------------------------------------------------------------------
@app.route("/plans")
@login_required
def plans():
    db = get_db()
    all_plans = db.execute("SELECT * FROM plans ORDER BY price").fetchall()
    my_subs = db.execute(
        """SELECT s.*, p.name as plan_name, p.duration_days
           FROM subscriptions s JOIN plans p ON s.plan_id=p.id
           WHERE s.user_id=? AND s.is_active=1 ORDER BY s.end_date DESC""",
        (session["user_id"],),
    ).fetchall()
    return render_template("plans.html", plans=all_plans, my_subs=my_subs)


@app.route("/plans/purchase/<int:plan_id>", methods=["POST"])
@login_required
def purchase_plan(plan_id):
    db = get_db()
    plan = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not plan:
        flash("존재하지 않는 이용권입니다.", "error")
        return redirect(url_for("plans"))
    start = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=plan["duration_days"])).strftime("%Y-%m-%d")
    db.execute(
        "INSERT INTO subscriptions (user_id, plan_id, start_date, end_date) VALUES (?,?,?,?)",
        (session["user_id"], plan_id, start, end),
    )
    db.execute(
        "INSERT INTO payments (user_id, amount, payment_type, description) VALUES (?,?,?,?)",
        (session["user_id"], plan["price"], "plan", plan["name"]),
    )
    db.execute(
        "UPDATE subscriptions SET is_active=0 WHERE user_id=? AND id != last_insert_rowid()",
        (session["user_id"],),
    )
    db.commit()
    flash(f"{plan['name']} 구매 완료! ({start} ~ {end})", "success")
    return redirect(url_for("plans"))


@app.route("/payments")
@login_required
def payment_history():
    db = get_db()
    payments = db.execute(
        "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC",
        (session["user_id"],),
    ).fetchall()
    total = sum(p["amount"] for p in payments)
    return render_template("payments.html", payments=payments, total=total)


# ---------------------------------------------------------------------------
# Routes — Admin Dashboard
# ---------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    auto_expire_reservations(db)
    total_users = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0]
    total_seats = db.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
    occupied_seats = db.execute("SELECT COUNT(*) FROM seats WHERE is_occupied=1").fetchone()[0]
    total_revenue = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
    today_revenue = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(created_at)=date('now','localtime')"
    ).fetchone()[0]
    active_subs = db.execute("SELECT COUNT(*) FROM subscriptions WHERE is_active=1").fetchone()[0]
    active_reservations = db.execute(
        "SELECT COUNT(*) FROM reservations WHERE status IN ('reserved','checked_in')"
    ).fetchone()[0]
    expired_count = db.execute(
        "SELECT COUNT(*) FROM reservations WHERE status IN ('expired','session_expired')"
    ).fetchone()[0]

    recent_payments = db.execute(
        """SELECT p.*, u.username FROM payments p JOIN users u ON p.user_id=u.id
           ORDER BY p.created_at DESC LIMIT 10"""
    ).fetchall()
    seats = db.execute(
        """SELECT s.*, u.username FROM seats s LEFT JOIN users u ON s.current_user_id=u.id
           ORDER BY s.seat_number"""
    ).fetchall()
    daily_rev = db.execute(
        """SELECT date(created_at) as day, SUM(amount) as total
           FROM payments WHERE created_at >= datetime('now','localtime','-7 days')
           GROUP BY date(created_at) ORDER BY day"""
    ).fetchall()

    # recent reservations with QR status + remaining time
    recent_res = db.execute(
        """SELECT r.*, s.seat_number, u.username
           FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           JOIN users u ON r.user_id=u.id
           ORDER BY r.created_at DESC LIMIT 15"""
    ).fetchall()

    # 각 예약의 남은 시간 계산
    res_with_remaining = []
    for r in recent_res:
        r_dict = dict(r)
        if r["status"] == "reserved":
            r_dict["remaining"] = format_remaining(calc_remaining_seconds(r["qr_expires_at"]))
        elif r["status"] == "checked_in":
            r_dict["remaining"] = format_remaining(calc_remaining_seconds(r["session_expires_at"]))
        else:
            r_dict["remaining"] = "-"
        res_with_remaining.append(r_dict)

    return render_template(
        "admin.html",
        total_users=total_users,
        total_seats=total_seats,
        occupied_seats=occupied_seats,
        total_revenue=total_revenue,
        today_revenue=today_revenue,
        active_subs=active_subs,
        active_reservations=active_reservations,
        expired_count=expired_count,
        recent_payments=recent_payments,
        seats=seats,
        daily_rev=daily_rev,
        recent_res=res_with_remaining,
        qr_expire_minutes=QR_EXPIRE_MINUTES,
        session_expire_minutes=SESSION_EXPIRE_MINUTES,
    )


@app.route("/admin/seats/manage")
@admin_required
def manage_seats():
    db = get_db()
    seats = db.execute("SELECT * FROM seats ORDER BY seat_number").fetchall()
    return render_template("manage_seats.html", seats=seats)


@app.route("/admin/seats/add", methods=["POST"])
@admin_required
def add_seat():
    seat_number = request.form["seat_number"].strip()
    zone = request.form.get("zone", "일반").strip()
    db = get_db()
    if db.execute("SELECT id FROM seats WHERE seat_number=?", (seat_number,)).fetchone():
        flash("이미 존재하는 좌석 번호입니다.", "error")
        return redirect(url_for("manage_seats"))
    db.execute("INSERT INTO seats (seat_number, zone) VALUES (?,?)", (seat_number, zone))
    db.commit()
    flash(f"좌석 {seat_number} 추가됨.", "success")
    return redirect(url_for("manage_seats"))


@app.route("/admin/seats/delete/<int:seat_id>", methods=["POST"])
@admin_required
def delete_seat(seat_id):
    db = get_db()
    db.execute("DELETE FROM seats WHERE id=?", (seat_id,))
    db.commit()
    flash("좌석 삭제됨.", "success")
    return redirect(url_for("manage_seats"))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.route("/api/seats")
def api_seats():
    db = get_db()
    auto_expire_reservations(db)
    seats = db.execute("SELECT * FROM seats ORDER BY seat_number").fetchall()
    return jsonify([
        {
            "id": s["id"],
            "seat_number": s["seat_number"],
            "zone": s["zone"],
            "is_occupied": bool(s["is_occupied"]),
            "occupied_since": s["occupied_since"],
        }
        for s in seats
    ])


@app.route("/api/my-reservation")
@login_required
def api_my_reservation():
    """남은 시간을 JSON으로 반환 (프론트엔드 새로고침용)."""
    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        """SELECT r.*, s.seat_number, s.zone FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           WHERE r.user_id=? AND r.status IN ('reserved','checked_in')
           ORDER BY r.created_at DESC LIMIT 1""",
        (session["user_id"],),
    ).fetchone()
    if not res:
        return jsonify({"active": False})
    if res["status"] == "reserved":
        remaining = calc_remaining_seconds(res["qr_expires_at"])
        label = "체크인 만료까지"
    else:
        remaining = calc_remaining_seconds(res["session_expires_at"])
        label = "이용 시간 종료까지"
    return jsonify({
        "active": True,
        "status": res["status"],
        "seat_number": res["seat_number"],
        "remaining_seconds": remaining,
        "remaining_label": label,
        "remaining_text": format_remaining(remaining),
    })


# ---------------------------------------------------------------------------
# Hardware API — QR 스캐너 장치용 JSON 엔드포인트
# ---------------------------------------------------------------------------
# 출입문 장치(Raspberry Pi / ESP32)가 QR 토큰을 전송하면
# JSON으로 결과를 반환. 브라우저용(/qr/checkin)과 분리됨.
#
# 사용 방법:
#   POST /api/door/checkin   {"token": "xxx"}   → 입실
#   POST /api/door/checkout  {"token": "xxx"}   → 출실
#   POST /api/door/verify    {"token": "xxx"}   → 상태만 확인 (문 개폐 X)
#
# 성공 응답:
#   {"success": true, "action": "checkin", "seat_number": "A1",
#    "username": "hong", "remaining_seconds": 14399, "message": "입실 완료"}
#
# 실패 응답:
#   {"success": false, "error": "QR 코드가 만료되었습니다"}

@app.route("/api/door/verify", methods=["POST"])
def api_door_verify():
    """QR 토큰 검증만 수행 (문 개폐하지 않음). 스캐너가 미리 확인용."""
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"success": False, "error": "토큰이 없습니다."}), 400

    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        """SELECT r.*, s.seat_number, s.zone, u.username
           FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           JOIN users u ON r.user_id=u.id
           WHERE r.qr_token=?""",
        (token,),
    ).fetchone()
    if not res:
        return jsonify({"success": False, "error": "유효하지 않은 QR 코드입니다."}), 404

    if res["status"] in ("cancelled", "completed"):
        return jsonify({"success": False, "error": "이 예약은 이미 종료되었습니다."})
    if res["status"] == "expired":
        return jsonify({"success": False, "error": "QR 코드가 만료되었습니다."})
    if res["status"] == "session_expired":
        return jsonify({"success": False, "error": "이용 시간이 종료되었습니다."})

    if res["status"] == "reserved":
        remaining = calc_remaining_seconds(res["qr_expires_at"])
        return jsonify({
            "success": True,
            "action": "checkin_ready",
            "seat_number": res["seat_number"],
            "zone": res["zone"],
            "username": res["username"],
            "remaining_seconds": remaining,
            "message": f"입실 가능 — {res['seat_number']} 좌석"
        })
    elif res["status"] == "checked_in":
        remaining = calc_remaining_seconds(res["session_expires_at"])
        return jsonify({
            "success": True,
            "action": "checkout_ready",
            "seat_number": res["seat_number"],
            "zone": res["zone"],
            "username": res["username"],
            "remaining_seconds": remaining,
            "message": f"퇴실 가능 — {res['seat_number']} 좌석"
        })
    return jsonify({"success": False, "error": "알 수 없는 상태입니다."})


@app.route("/api/door/checkin", methods=["POST"])
def api_door_checkin():
    """하드웨어 QR 스캐너용 입실 API — JSON 반환."""
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"success": False, "error": "토큰이 없습니다."}), 400

    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        """SELECT r.*, s.seat_number, s.zone, u.username
           FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           JOIN users u ON r.user_id=u.id
           WHERE r.qr_token=? AND r.status='reserved'""",
        (token,),
    ).fetchone()
    if not res:
        # 이미 만료되었는지 확인
        expired_res = db.execute(
            "SELECT status FROM reservations WHERE qr_token=?", (token,)
        ).fetchone()
        if expired_res:
            if expired_res["status"] == "expired":
                return jsonify({"success": False, "error": "QR 코드가 만료되었습니다."})
            if expired_res["status"] == "checked_in":
                return jsonify({"success": False, "error": "이미 입실 중입니다. 퇴실 QR을 스캔하세요."})
            return jsonify({"success": False, "error": f"입실할 수 없습니다. 상태: {expired_res['status']}"})
        return jsonify({"success": False, "error": "유효하지 않은 QR 코드입니다."}), 404

    # 만료 체크
    if res["qr_expires_at"]:
        remaining = calc_remaining_seconds(res["qr_expires_at"])
        if remaining is not None and remaining <= 0:
            db.execute("UPDATE reservations SET status='expired' WHERE id=?", (res["id"],))
            db.commit()
            return jsonify({"success": False, "error": "QR 코드가 만료되었습니다."})

    # 좌석 확인
    seat = db.execute("SELECT * FROM seats WHERE id=?", (res["seat_id"],)).fetchone()
    if seat["is_occupied"]:
        return jsonify({"success": False, "error": "해당 좌석이 이미 사용 중입니다."})

    # 입실 처리
    now = datetime.now()
    session_expires = now + timedelta(minutes=SESSION_EXPIRE_MINUTES)
    db.execute(
        """UPDATE reservations SET check_in_time=?, status='checked_in', session_expires_at=?
           WHERE id=?""",
        (fmt(now), fmt(session_expires), res["id"]),
    )
    db.execute(
        "UPDATE seats SET is_occupied=1, current_user_id=?, occupied_since=? WHERE id=?",
        (res["user_id"], fmt(now), res["seat_id"]),
    )
    db.commit()

    remaining = calc_remaining_seconds(fmt(session_expires))
    relay_ok, relay_msg = trigger_relay("checkin")
    return jsonify({
        "success": True,
        "action": "checkin",
        "seat_number": res["seat_number"],
        "zone": res["zone"],
        "username": res["username"],
        "remaining_seconds": remaining,
        "session_expires_at": fmt(session_expires),
        "relay_triggered": relay_ok,
        "relay_message": relay_msg,
        "message": f"입실 완료 — {res['seat_number']} 좌석 (이용시간 {SESSION_EXPIRE_MINUTES}분)"
    })


@app.route("/api/door/checkout", methods=["POST"])
def api_door_checkout():
    """하드웨어 QR 스캐너용 출실 API — JSON 반환."""
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"success": False, "error": "토큰이 없습니다."}), 400

    db = get_db()
    auto_expire_reservations(db)
    res = db.execute(
        """SELECT r.*, s.seat_number, s.zone, u.username
           FROM reservations r
           JOIN seats s ON r.seat_id=s.id
           JOIN users u ON r.user_id=u.id
           WHERE r.qr_token=? AND r.status='checked_in'""",
        (token,),
    ).fetchone()
    if not res:
        expired_res = db.execute(
            "SELECT status FROM reservations WHERE qr_token=?", (token,)
        ).fetchone()
        if expired_res:
            if expired_res["status"] == "session_expired":
                return jsonify({"success": False, "error": "이용 시간이 종료되었습니다."})
            if expired_res["status"] == "reserved":
                return jsonify({"success": False, "error": "아직 입실하지 않았습니다."})
            if expired_res["status"] == "completed":
                return jsonify({"success": False, "error": "이미 퇴실 처리되었습니다."})
            return jsonify({"success": False, "error": f"출실할 수 없습니다. 상태: {expired_res['status']}"})
        return jsonify({"success": False, "error": "유효하지 않은 QR 코드입니다."}), 404

    now = fmt(datetime.now())
    db.execute(
        "UPDATE reservations SET check_out_time=?, status='completed' WHERE id=?",
        (now, res["id"]),
    )
    db.execute(
        "UPDATE seats SET is_occupied=0, current_user_id=NULL, occupied_since=NULL WHERE id=?",
        (res["seat_id"],),
    )
    db.commit()

    relay_ok, relay_msg = trigger_relay("checkout")
    return jsonify({
        "success": True,
        "action": "checkout",
        "seat_number": res["seat_number"],
        "username": res["username"],
        "relay_triggered": relay_ok,
        "relay_message": relay_msg,
        "message": f"출실 완료 — {res['seat_number']} 좌석"
    })


# ---------------------------------------------------------------------------
# 관리자 — 릴레이 설정 API
# ---------------------------------------------------------------------------

@app.route("/api/relay/config", methods=["GET"])
@login_required
def api_relay_get_config():
    if not session.get("is_admin"):
        return jsonify({"error": "관리자 권한 필요"}), 403
    db = get_db()
    row = db.execute("SELECT * FROM relay_config WHERE id=1").fetchone()
    if not row:
        return jsonify({"enabled": 0, "device_type": "shelly", "ip_address": "", "port": 80,
                         "relay_channel": 0, "username": "", "password": "",
                         "open_duration_ms": 3000, "last_triggered_at": None,
                         "last_trigger_result": None})
    return jsonify({k: row[k] for k in row.keys()})


@app.route("/api/relay/config", methods=["POST"])
@login_required
def api_relay_set_config():
    if not session.get("is_admin"):
        return jsonify({"error": "관리자 권한 필요"}), 403
    data = request.get_json(silent=True) or {}
    db = get_db()
    db.execute("""
        UPDATE relay_config SET
            enabled=?, device_type=?, ip_address=?, port=?,
            relay_channel=?, username=?, password=?, open_duration_ms=?
        WHERE id=1
    """, (
        1 if data.get("enabled") else 0,
        data.get("device_type", "shelly"),
        data.get("ip_address", "").strip(),
        int(data.get("port", 80)),
        int(data.get("relay_channel", 0)),
        data.get("username", "").strip(),
        data.get("password", "").strip(),
        int(data.get("open_duration_ms", 3000)),
    ))
    db.commit()
    return jsonify({"success": True, "message": "릴레이 설정이 저장되었습니다."})


@app.route("/api/relay/test", methods=["POST"])
@login_required
def api_relay_test():
    if not session.get("is_admin"):
        return jsonify({"error": "관리자 권한 필요"}), 403
    ok, msg = trigger_relay("test")
    return jsonify({"success": ok, "message": msg})


# ---------------------------------------------------------------------------
# 휴대폰 QR 스캐너 페이지 (/scanner)
# ---------------------------------------------------------------------------
# 구안 스마트폰의 브라우저 카메라로 QR 코드를 인식하여
# 자동으로 입실/퇴실 처리. 별도 하드웨어 없이 휴대폰만으로 동작.
#
# 동작 흐름:
#   1. 카메라 실시간 스캔 → QR 토큰 추출 (jsQR 라이브러리)
#   2. /api/door/verify 로 상태 확인 (입실 가능? 퇴실 가능?)
#   3. 상태에 따라 /api/door/checkin 또는 /api/door/checkout 자동 호출
#   4. 결과를 화면에 표시 (녹색=성공, 적색=실패)

@app.route("/scanner")
def scanner():
    """휴대폰 QR 스캐너 페이지 - 카메라로 QR 인식 후 자동 입실/퇴실."""
    return render_template("scanner.html")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)