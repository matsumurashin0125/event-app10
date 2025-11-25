# main.py  — Gmail + ICS 自動送信版
# --- CHANGES/ADDITIONS marked with comments "# --- ADDED" or "# --- CHANGED"

import os
import uuid
import logging
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session
import traceback

from models import db, Candidate, Confirmed, Attendance

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # --- CHANGED: secret from env optionally
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "fixed-secret-key-abcde-12345")

    # --- CHANGED: DB設定 unchanged, same as before but read from env
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL が設定されていません")

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # logger
    if not app.debug:
        logging.basicConfig(level=logging.INFO)

    # --- ADDED: Member emails mapping (do NOT pass to templates)
    # Set these in Render / environment:
    # MAIL_MATSUMURA, MAIL_YAMABI, MAIL_YAMANE, MAIL_OKUSAKO, MAIL_KAWASAKI
    MEMBER_EMAILS = {
        "松村": os.environ.get("MAIL_MATSUMURA"),
        "山火": os.environ.get("MAIL_YAMABI"),
        "山根": os.environ.get("MAIL_YAMANE"),
        "奥迫": os.environ.get("MAIL_OKUSAKO"),
        "川崎": os.environ.get("MAIL_KAWASAKI"),
    }

    # --- ADDED: Gmail SMTP settings from env
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("GMAIL_USER")   # required
    SMTP_PASS = os.environ.get("GMAIL_PASS")   # required (app password)

    # timezone
    LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Tokyo"))

    # ------------------------------
    # Routes (mostly unchanged)
    # ------------------------------
    @app.route("/")
    @app.route("/home")
    def home():
        return render_template("home.html")

    # ------------------------------
    # 追加：ユーザー名の選択・保存
    # ------------------------------
    @app.route("/set_name", methods=["GET", "POST"])
    def set_name():
        members = ["松村", "山火", "山根", "奥迫", "川崎"]

        if request.method == "POST":
            # 選択した名前をセッションへ保存
            session["user_name"] = request.form["user_name"]
            return redirect(url_for("register"))

        return render_template("set_name.html", members=members)

    @app.route("/admin")
    def admin_menu():
        return render_template("admin_menu.html")

    @app.route("/candidate", methods=["GET", "POST"])
    def candidate():
        gyms = ["中平井", "平井", "西小岩", "北小岩", "南小岩"]
        times = []
        for h in range(18, 23):
            times.append(f"{h:02d}:00")
            times.append(f"{h:02d}:30")
        times = times[:-1]
        today = datetime.now(tz=LOCAL_TZ)
        base = (today.replace(day=1) + timedelta(days=92)).replace(day=1)
        years = [base.year, base.year + 1]
        months = list(range(1, 13))
        days = list(range(1, 32))
        confirmed_ids = { c.candidate_id for c in Confirmed.query.all() }

        if request.method == "POST":
            cand = Candidate(
                year=int(request.form["year"]),
                month=int(request.form["month"]),
                day=int(request.form["day"]),
                gym=request.form["gym"],
                start=request.form["start"],
                end=request.form["end"]
            )
            db.session.add(cand)
            db.session.commit()
            return render_template("candidate.html",
                                   years=years, months=months, days=days,
                                   gyms=gyms, times=times,
                                   selected_year=cand.year, selected_month=cand.month, selected_day=cand.day,
                                   selected_gym=cand.gym, selected_start=cand.start, selected_end=cand.end,
                                   confirmed_ids=confirmed_ids)

        return render_template("candidate.html",
                               years=years, months=months, days=days,
                               gyms=gyms, times=times,
                               selected_year=base.year, selected_month=base.month, selected_day=base.day,
                               selected_gym="中平井", selected_start="18:00", selected_end="19:00",
                               confirmed_ids=confirmed_ids)

    @app.route("/confirm", methods=["GET", "POST"])
    def confirm():
        candidates = Candidate.query.order_by(
            Candidate.year.asc(), Candidate.month.asc(), Candidate.day.asc(), Candidate.start.asc()
        ).all()
        if request.method == "POST":
            c_id = int(request.form["candidate_id"])
            exists = Confirmed.query.filter_by(candidate_id=c_id).first()
            if not exists:
                db.session.add(Confirmed(candidate_id=c_id))
                db.session.commit()
            return redirect(url_for("confirm"))
        confirmed = (
            db.session.query(Confirmed, Candidate)
            .join(Candidate, Confirmed.candidate_id == Candidate.id)
            .order_by(Candidate.year.asc(), Candidate.month.asc(), Candidate.day.asc(), Candidate.start.asc())
            .all()
        )
        confirmed_list = db.session.query(Confirmed).all()
        confirmed_ids = [c.candidate_id for c in confirmed_list]

        def format_candidate(c):
            d = date(c.year, c.month, c.day)
            youbi = ["月","火","水","木","金","土","日"][d.weekday()]
            return {"id": c.id, "gym": c.gym, "start": c.start, "end": c.end, "md": f"{c.month}/{c.day}（{youbi}）"}
        candidates_fmt = [format_candidate(c) for c in candidates]
        confirmed_fmt = []
        for cnf, c in confirmed:
            d = date(c.year, c.month, c.day)
            youbi = ["月","火","水","木","金","土","日"][d.weekday()]
            confirmed_fmt.append((cnf, {"gym": c.gym, "start": c.start, "end": c.end, "md": f"{c.month}/{c.day}（{youbi}）"}))

        attendance_summary = {}
        for cnf, c in confirmed:
            event_id = cnf.id
            attendance_list = Attendance.query.filter_by(event_id=event_id).all()
    
            attend_members = [a.name for a in attendance_list if (getattr(a, "status", None) or "") == "attend"]
            absent_members = [a.name for a in attendance_list if (getattr(a, "status", None) or "") == "absent"]
    
            attendance_summary[event_id] = {
                "attend_count": len(attend_members),
                "absent_count": len(absent_members),
                "attend_members": attend_members,
                "absent_members": absent_members,
            }
            
        return render_template(
            "confirm.html",
            candidates=candidates_fmt,
            confirmed=confirmed_fmt,
            confirmed_ids=confirmed_ids,
            attendance_summary=attendance_summary
        )

    @app.route("/confirm/<int:candidate_id>/unconfirm", methods=["POST"])
    def unconfirm(candidate_id):
        conf = Confirmed.query.filter_by(candidate_id=candidate_id).first()
        if conf:
            db.session.delete(conf)
            db.session.commit()
        return redirect(url_for("confirm"))

    # --------------------------------------------
    # 参加者編集ページ（表示）
    # --------------------------------------------
    @app.route("/manage_event/<int:event_id>", methods=["GET"])
    def manage_event_attendance(event_id):
        event = Confirmed.query.get_or_404(event_id)
        candidate = Candidate.query.get_or_404(event.candidate_id)
    
        # イベント情報フォーマット
        from datetime import date
        d = date(candidate.year, candidate.month, candidate.day)
        youbi = ["月","火","水","木","金","土","日"][d.weekday()]
    
        event_info = {
            "md": f"{candidate.month}/{candidate.day}（{youbi}）",
            "gym": candidate.gym,
            "start": candidate.start,
            "end": candidate.end,
        }
    
        # このイベントの参加者一覧
        attendance = Attendance.query.filter_by(event_id=event_id).all()
    
        return render_template(
            "manage_event_attendance.html",
            event_info=event_info,
            attendance=attendance
        )
    
    
    # --------------------------------------------
    # 参加ステータス更新
    # --------------------------------------------
    @app.route("/update_attendance/<int:attendance_id>", methods=["POST"])
    def update_attendance(attendance_id):
        record = Attendance.query.get_or_404(attendance_id)
    
        new_status = request.form.get("status")
        if new_status not in ["attend", "absent"]:
            return "Invalid status", 400
    
        record.status = new_status
        db.session.commit()
    
        return redirect(url_for("confirm"))

    @app.route("/attendance/<int:id>/delete", methods=["POST"])
    def delete_attendance(id):
        att = Attendance.query.get_or_404(id)
        candidate_id = att.event.candidate_id
        db.session.delete(att)
        db.session.commit()

        return redirect(url_for("confirm"))

    @app.route("/register", methods=["GET"])
    def register():
        user_name = session.get("user_name")
        candidates = Candidate.query.order_by(
            Candidate.year.asc(), Candidate.month.asc(), Candidate.day.asc(), Candidate.start.asc()
        ).all()

        # candidates に confirmed_id を付与する
        for c in candidates:
            cnf = Confirmed.query.filter_by(candidate_id=c.id).first()
            c.confirmed_id = cnf.id if cnf else None

        # --- 追加：Confirmed を取得して attendance_summary を作る ---
        attendance_summary = {}
        confirmed_events = Confirmed.query.all()

        for cnf in confirmed_events:
            event_id = cnf.id
            attendance_list = Attendance.query.filter_by(event_id=event_id).all()

            attend_members = [a.name for a in attendance_list if (getattr(a, "status", None) or "") == "attend"]
            absent_members = [a.name for a in attendance_list if (getattr(a, "status", None) or "") == "absent"]

            attendance_summary[event_id] = {
                "attend_count": len(attend_members),
                "absent_count": len(absent_members),
                "attend_members": attend_members,
                "absent_members": absent_members,
            }

        return render_template(
            "register_select.html",
            candidates=candidates,
            user_name=user_name,
            attendance_summary=attendance_summary   # ← 追加
        )
    
    @app.route("/register/event/<int:candidate_id>", methods=["GET", "POST"])
    def register_event(candidate_id):
        candidate = Candidate.query.get_or_404(candidate_id)
    
        # Confirmed が存在しない場合は自動作成
        event = Confirmed.query.filter_by(candidate_id=candidate_id).first()
        if not event:
            event = Confirmed(candidate_id=candidate_id)
            db.session.add(event)
            db.session.commit()
        
        members = ["松村", "山火", "山根", "奥迫", "川崎"]

        default_name = session.get("user_name")
    
        if request.method == "POST":
    
            # ---- ここが重要：HTML の値を DB 用に統一する ----
            raw_status = request.form["status"]
    
            if raw_status in ["参加", "attend"]:
                status = "attend"
            elif raw_status in ["不参加", "absent"]:
                status = "absent"
            else:
                status = "pending"     # 「未定」「未回答」などはこちらに
    
            # 既にその人の出欠があるかチェック
            att = Attendance.query.filter_by(event_id=event.id, name=request.form["name"]).first()
    
            if att:
                # 既存の出欠を更新
                att.status = status
            else:
                # 新規出欠を保存
                att = Attendance(
                    event_id=event.id,
                    name=request.form["name"],
                    status=status
                )
                db.session.add(att)
    
            db.session.commit()

             # ---- メール送信（参加の場合）----
            if status == "attend":
                name = request.form["name"]              # ★ 重要：名前を確定
                recipient_email = MEMBER_EMAILS.get(name)
            
                if recipient_email:
                    try:
                        send_ics_via_sendgrid(candidate, name, recipient_email)
                    except Exception as e:
                        app.logger.error("ICS send failed: %s", e)
                        app.logger.error(traceback.format_exc())

            return redirect(url_for("register"))
    
        attendance = Attendance.query.filter_by(event_id=event.id).all()
    
        return render_template(
            "register_form.html",
            candidate=candidate,
            attendance=attendance,
            members=members,
            default_name=default_name   
        )


    @app.route("/candidate/<int:id>/edit", methods=["GET", "POST"])
    def edit_candidate(id):
        cand = Candidate.query.get_or_404(id)
        gyms = ["中平井", "平井", "西小岩", "北小岩", "南小岩"]
        times = []
        for h in range(18, 23):
            times.append(f"{h:02d}:00")
            times.append(f"{h:02d}:30")
        times = times[:-1]
        if request.method == "POST":
            cand.year = int(request.form["year"])
            cand.month = int(request.form["month"])
            cand.day = int(request.form["day"])
            cand.gym = request.form["gym"]
            cand.start = request.form["start"]
            cand.end = request.form["end"]
            db.session.commit()
            return redirect(url_for("confirm"))
        return render_template("edit_candidate.html", cand=cand, gyms=gyms, times=times)

    @app.route("/candidate/<int:id>/delete", methods=["POST"])
    def delete_candidate(id):
        cand = Candidate.query.get_or_404(id)
        Attendance.query.filter(
            Attendance.event_id.in_(
                db.session.query(Confirmed.id).filter_by(candidate_id=id)
            )
        ).delete(synchronize_session=False)
        Confirmed.query.filter_by(candidate_id=id).delete()
        db.session.delete(cand)
        db.session.commit()
        return redirect(url_for("admin_menu"))

    @app.route("/attendance/<int:id>/edit", methods=["GET", "POST"])
    def edit_attendance(id):
        att = Attendance.query.get_or_404(id)
        members = ["松村", "山火", "山根", "奥迫", "川崎"]
    
        if request.method == "POST":
            # 画面入力（日本語ラベルや既にattend/absentが来ても対応）
            raw_name = request.form.get("name", "").strip()
            raw_status = request.form.get("status", "").strip()
    
            # 名前の更新（そのまま保存）
            if raw_name:
                att.name = raw_name
    
            # ステータスを統一して保存（DB中は "attend"/"absent"/"pending"）
            if raw_status in ["参加", "attend", "attending"]:
                att.status = "attend"
            elif raw_status in ["不参加", "欠席", "absent"]:
                att.status = "absent"
            else:
                # 未回答／未定などは "pending" とする（テンプレ側で未回答表示）
                att.status = "pending"
    
            db.session.commit()
    
            # 編集元ページへ戻す（ユーザー用画面を維持）
            return redirect(url_for("candidate"))
    
        # GET: 編集フォーム表示（テンプレートは下に示します）
        return render_template("edit_attendance.html", att=att, members=members)


    # --- ADDED: ICS creation and Gmail send function
    def make_ics(summary, description, location, dtstart_local: datetime, dtend_local: datetime, uid=None):
        """
        Create ICS string. Input datetimes must be timezone-aware in local tz.
        We convert to UTC and produce Z-suffixed timestamps (widely compatible).
        """
        if uid is None:
            uid = f"{uuid.uuid4()}@yourapp.local"

        dtstart_utc = dtstart_local.astimezone(timezone.utc)
        dtend_utc = dtend_local.astimezone(timezone.utc)
        dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        dtstart_str = dtstart_utc.strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend_utc.strftime("%Y%m%dT%H%M%SZ")

        def esc(s: str):
            return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")

        s = esc(summary); d = esc(description); l = esc(location)

        ics = (
            "BEGIN:VCALENDAR\r\n"
            "PRODID:-//YourApp//EN\r\n"
            "VERSION:2.0\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{dtstamp}\r\n"
            f"DTSTART:{dtstart_str}\r\n"
            f"DTEND:{dtend_str}\r\n"
            f"SUMMARY:{s}\r\n"
            f"DESCRIPTION:{d}\r\n"
            f"LOCATION:{l}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        return ics

    def make_google_calendar_link(title, details, location, start_local: datetime, end_local: datetime):
        """
        Create a Google Calendar 'quick add' link (prefilled event).
        Format for dates: YYYYMMDDTHHMMSSZ or local with timezone? We use UTC times with Z.
        Note: Google expects ISO without separators: 20250110T090000Z
        """
        start_utc = start_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end_utc = end_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = "https://www.google.com/calendar/render?action=TEMPLATE"
        from urllib.parse import quote_plus
        params = (
            f"&text={quote_plus(title)}"
            f"&details={quote_plus(details)}"
            f"&location={quote_plus(location)}"
            f"&dates={start_utc}/{end_utc}"
        )
        return base + params

    import base64
    import pytz
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
    
    
    def send_ics_via_sendgrid(candidate, recipient_name, recipient_email, local_tz="Asia/Tokyo"):
        """
        SendGrid を使って iPhone / Google / Outlook で必ず開ける ICS を送信する
        """
    
        # ==========
        # 1)  ローカル時刻 → aware datetime
        # ==========
        tz = pytz.timezone(local_tz)
    
        dt_start = tz.localize(datetime(
            candidate.year,
            candidate.month,
            candidate.day,
            int(candidate.start.split(":")[0]),
            int(candidate.start.split(":")[1])
        ))
    
        dt_end = tz.localize(datetime(
            candidate.year,
            candidate.month,
            candidate.day,
            int(candidate.end.split(":")[0]),
            int(candidate.end.split(":")[1])
        ))
    
        # ==========
        # 2)  iPhone 互換の ICS を生成（完全版）
        #    Apple は UTC(Z) と METHOD:REQUEST が必須
        # ==========
        dtstamp_utc = dt_start.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
        start_utc = dt_start.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
        end_utc = dt_end.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
    
        uid = f"{candidate.id}-{start_utc}@event-app.local"

        start_str = dt_start.strftime("%H:%M")
        end_str = dt_end.strftime("%H:%M")

        ics_content = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "METHOD:REQUEST\r\n"
            "PRODID:-//EventApp//JP\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:{uid}\r\n"
            "DTSTAMP:{dtstamp_utc}\r\n"
            "DTSTART:{start_utc}\r\n"
            "DTEND:{end_utc}\r\n"
            "SUMMARY:{location} ({start_str}〜{end_str})\r\n"
            "DESCRIPTION:{recipient_name} さんの参加登録です\r\n"
            "LOCATION:{location}\r\n"
            "STATUS:CONFIRMED\r\n"
            "SEQUENCE:0\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ).format(
            uid=uid,
            dtstamp_utc=dtstamp_utc,
            start_utc=start_utc,
            end_utc=end_utc,
            recipient_name=recipient_name,
            location=candidate.gym,
            start_str=start_str,
            end_str=end_str
        )
    
        # ==========
        # 3) Base64 エンコード（SendGrid 必須）
        # ==========
        encoded = base64.b64encode(ics_content.encode("utf-8")).decode()
    
        # ==========
        # 4) SendGrid メール作成
        # ==========
        message = Mail(
            from_email=(os.environ["FROM_EMAIL"], os.environ.get("FROM_NAME", "Event App")),
            to_emails=recipient_email,
            subject=f"【参加登録】カレンダーに追加できます",
            html_content=f"""
                <p>{recipient_name} さん、参加登録ありがとうございます。</p>
                <p>カレンダーに追加できる .ics ファイルを添付しています。</p>
                <p>iPhone・Google・Outlook 全てに対応しています。</p>
            """
        )
    
        # 添付ファイル
        attachment = Attachment()
        attachment.file_content = FileContent(encoded)
        attachment.file_type = FileType("text/calendar")
        attachment.file_name = FileName("event.ics")
        attachment.disposition = Disposition("attachment")
    
        message.attachment = attachment
    
        # ==========
        # 5) SendGrid 送信
        # ==========
        try:
            sg = SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
            response = sg.send(message)
            print("SendGrid Response:", response.status_code)
            return True
        except Exception as e:
            print("SendGrid Error:", e)
            return False

    # DB create
    with app.app_context():
        db.create_all()

    return app

app = create_app()
