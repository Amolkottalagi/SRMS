from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect
from database import get_db, engine, Base, SessionLocal
from config import Config

from models import (
    Admin, Student, Teacher, Subject, Marks,
    GradingScheme, Backlog, Notification, AuditLog,
    Verification, SystemSetting,
)
from utils.pdf_generator import generate_pdf
from datetime import datetime
import hashlib
import uuid
import qrcode
import io
import csv

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=Config.SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Create all tables
Base.metadata.create_all(bind=engine)


# ─── Flash message helpers ───────────────────────────────────────────

def flash(request: Request, message: str, category: str = "primary"):
    if "_messages" not in request.session:
        request.session["_messages"] = []
    request.session["_messages"].append({"message": message, "category": category})


def get_flashed_messages(request: Request):
    messages = request.session.pop("_messages", [])
    return [(m["category"], m["message"]) for m in messages]


# Register helpers in Jinja2 globals
templates.env.globals["get_flashed_messages"] = get_flashed_messages
def _url_for(name, **kwargs):
    """Template-compatible url_for that handles static files and routes."""
    if name == "static":
        # FastAPI StaticFiles uses 'path', but templates use 'filename'
        filename = kwargs.pop("filename", None)
        if filename:
            return f"/static/{filename}"
    return str(app.url_path_for(name, **kwargs))


templates.env.globals["url_for"] = _url_for



# ─── Helper context for every template ────────────────────────────────

def tpl(request: Request, template_name: str, context: dict | None = None):
    """Shortcut that always injects `request` and `session`."""
    ctx = {"session": request.session}
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name=template_name, context=ctx)




# ─── Business‑logic helpers (receive db session explicitly) ──────────

def get_grade_for_percentage(db: Session, percentage):
    try:
        schemes = db.query(GradingScheme).order_by(GradingScheme.min_pct.desc()).all()
        for s in schemes:
            if s.min_pct <= percentage <= s.max_pct:
                return s.grade_letter
    except Exception:
        pass
    if percentage >= 75:
        return "A"
    elif percentage >= 60:
        return "B"
    elif percentage >= 50:
        return "C"
    return "F"


def get_gp_for_score(db: Session, percentage):
    try:
        schemes = db.query(GradingScheme).order_by(GradingScheme.min_pct.desc()).all()
        for s in schemes:
            if s.min_pct <= percentage <= s.max_pct:
                return s.grade_point
    except Exception:
        pass
    if percentage >= 75:
        return 10.0
    elif percentage >= 60:
        return 8.0
    elif percentage >= 50:
        return 6.0
    return 0.0


def compute_gpa(db: Session, roll_no, semester=None):
    query = db.query(Marks).filter_by(roll_no=roll_no)
    if semester:
        query = query.filter_by(semester=semester)
    marks_records = query.all()

    total_credit_points = 0.0
    total_credits = 0

    for mr in marks_records:
        sub = mr.subject
        if sub:
            credits = sub.credits or 3
            gp = get_gp_for_score(db, mr.marks)
            total_credit_points += gp * credits
            total_credits += credits

    if total_credits == 0:
        return 0.0
    return round(total_credit_points / total_credits, 2)


def compute_rank(db: Session, course, semester, roll_no):
    from collections import defaultdict

    all_students_in_course = db.query(Student).filter_by(course=course).all()
    student_rolls = [s.roll_no for s in all_students_in_course]
    all_marks = db.query(Marks).filter_by(course=course, semester=semester).all()

    student_totals = defaultdict(int)
    for m in all_marks:
        if m.roll_no in student_rolls:
            student_totals[m.roll_no] += m.marks

    if not student_totals or roll_no not in student_totals:
        return None, 0, 0.0

    sorted_students = sorted(student_totals.items(), key=lambda x: x[1], reverse=True)

    rank = 1
    target_total = student_totals[roll_no]
    for r_no, total in sorted_students:
        if total > target_total:
            rank += 1

    total_students = len(student_totals)

    if total_students > 1:
        percentile = ((total_students - rank) / total_students) * 100
    else:
        percentile = 100.0

    return rank, total_students, round(percentile, 2)


def check_at_risk(db: Session, student):
    from collections import defaultdict

    student_marks = db.query(Marks).filter_by(roll_no=student.roll_no).all()
    sem_data = defaultdict(list)
    for sm in student_marks:
        sem_data[sm.semester].append(sm.marks)

    sorted_sems = sorted(sem_data.keys())
    sem_percentages = []
    for sem in sorted_sems:
        marks = sem_data[sem]
        pct = sum(marks) / len(marks) if marks else 0
        sem_percentages.append((sem, pct))

    threshold_setting = db.query(SystemSetting).filter_by(key="at_risk_threshold").first()
    threshold = float(threshold_setting.value) if threshold_setting else 55.0

    reasons = []

    if sem_percentages:
        latest_sem, latest_pct = sem_percentages[-1]
        if latest_pct < threshold:
            reasons.append(f"Latest percentage ({latest_pct:.1f}%) below threshold ({threshold:.1f}%)")

    if len(sem_percentages) >= 3:
        p1 = sem_percentages[-3][1]
        p2 = sem_percentages[-2][1]
        p3 = sem_percentages[-1][1]
        if p1 > p2 > p3:
            reasons.append(f"Declining trend: {p1:.1f}% → {p2:.1f}% → {p3:.1f}%")

    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def log_audit(db: Session, request: Request, action, target_roll_no, subject_id, old_value, new_value):
    try:
        log = AuditLog(
            actor_role=request.session.get("role", "system"),
            actor_id=request.session.get("username", "system"),
            action=action,
            target_roll_no=target_roll_no,
            subject_id=subject_id,
            old_value=old_value,
            new_value=new_value,
        )
        db.add(log)
    except Exception as e:
        print(f"Error logging audit entry: {e}")


def notify_user(db: Session, user_role, user_id, message):
    try:
        notif = Notification(
            user_role=user_role,
            user_id=str(user_id),
            message=message,
        )
        db.add(notif)
    except Exception as e:
        print(f"Error creating notification: {e}")


def get_analytics_summary(db: Session):
    from collections import defaultdict

    all_marks = db.query(Marks).all()
    grouped_marks = defaultdict(list)
    for m in all_marks:
        grouped_marks[(m.course, m.semester, m.roll_no)].append(m.marks)

    analytics_data = defaultdict(list)
    for (course, semester, roll_no), marks in grouped_marks.items():
        student_avg = sum(marks) / len(marks) if marks else 0
        analytics_data[(course, semester)].append(student_avg)

    summary = []
    for (course, semester), averages in analytics_data.items():
        total_students = len(averages)
        passed_students = sum(1 for avg in averages if avg >= 50)
        pass_pct = (passed_students / total_students * 100) if total_students > 0 else 0
        avg_marks = sum(averages) / total_students if total_students > 0 else 0
        summary.append(
            {
                "course": course,
                "semester": semester,
                "avg_marks": round(avg_marks, 2),
                "pass_percentage": round(pass_pct, 2),
                "total_students": total_students,
            }
        )
    summary.sort(key=lambda x: (x["course"], x["semester"]))
    return summary


# ─── ROUTES ─────────────────────────────────────────────────────────

# --- PORTAL HOMEPAGE ---
@app.get("/", name="home")
async def home(request: Request, db: Session = Depends(get_db)):
    if "role" in request.session:
        role = request.session["role"]
        if role == "admin":
            return RedirectResponse(url=app.url_path_for("admin_dashboard"), status_code=303)
        elif role == "teacher":
            return RedirectResponse(url=app.url_path_for("teacher_dashboard"), status_code=303)
        elif role == "student":
            return RedirectResponse(url=app.url_path_for("student_dashboard"), status_code=303)
    return tpl(request, "index.html")


# --- LOGINS & AUTHENTICATION ---
@app.get("/login/{role}", name="login")
async def login(role: str, request: Request):
    if role not in ["admin", "teacher", "student"]:
        return RedirectResponse(url=app.url_path_for("home"), status_code=303)
    return tpl(request, "login.html", {"role": role})


@app.post("/login/{role}", name="login_post")
async def login_post(role: str, request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    if role == "admin":
        username = form.get("username")
        password = form.get("password")
        admin = db.query(Admin).filter_by(username=username, password=password).first()
        if admin:
            request.session["role"] = "admin"
            request.session["username"] = admin.username
            flash(request, "Admin successfully logged in.", "success")
            return RedirectResponse(url=app.url_path_for("admin_dashboard"), status_code=303)
        else:
            flash(request, "Invalid Admin Credentials.", "error")

    elif role == "teacher":
        teacher_id = form.get("teacher_id")
        password = form.get("password")
        teacher = db.query(Teacher).filter_by(teacher_id=teacher_id, password=password).first()
        if teacher:
            request.session["role"] = "teacher"
            request.session["teacher_db_id"] = teacher.id
            request.session["username"] = teacher.name
            request.session["teacher_id"] = teacher.teacher_id
            request.session["course"] = teacher.course
            flash(request, f"Welcome, Prof. {teacher.name}", "success")
            return RedirectResponse(url=app.url_path_for("teacher_dashboard"), status_code=303)
        else:
            flash(request, "Invalid Teacher ID or Password.", "error")

    elif role == "student":
        roll_no = form.get("roll_no")
        password = form.get("password")
        student = db.query(Student).filter_by(roll_no=roll_no).first()
        if student:
            dob_ddmmyyyy = student.dob.strftime("%d%m%Y") if student.dob else ""
            dob_yyyymmdd = student.dob.strftime("%Y%m%d") if student.dob else ""
            if password in [dob_ddmmyyyy, dob_yyyymmdd]:
                request.session["role"] = "student"
                request.session["roll_no"] = student.roll_no
                request.session["username"] = student.name
                flash(request, f"Welcome, {student.name}", "success")
                return RedirectResponse(url=app.url_path_for("student_dashboard"), status_code=303)
            else:
                flash(request, "Invalid Date of Birth. Use format DDMMYYYY (e.g. 15052004).", "error")
        else:
            flash(request, "No student profile found for this roll number.", "error")

    return RedirectResponse(url=app.url_path_for("login", role=role), status_code=303)


@app.get("/logout", name="logout")
async def logout(request: Request):
    request.session.clear()
    flash(request, "Logged out successfully.", "success")
    return RedirectResponse(url=app.url_path_for("home"), status_code=303)


# --- ADMIN VIEWS ---
@app.get("/admin/dashboard", name="admin_dashboard")
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    student_count = db.query(Student).count()
    teacher_count = db.query(Teacher).count()
    subject_count = db.query(Subject).count()
    stats = {"students": student_count, "teachers": teacher_count, "subjects": subject_count}
    return tpl(request, "admin_dashboard.html", {"stats": stats})


# --- STUDENTS CRUD ---
@app.get("/admin/students", name="view_students")
async def view_students(request: Request, db: Session = Depends(get_db)):
    from collections import defaultdict

    students = db.query(Student).order_by(Student.roll_no).all()

    for s in students:
        is_at_risk, reason = check_at_risk(db, s)
        s.is_at_risk = is_at_risk
        s.at_risk_reason = reason

    grouped = defaultdict(list)
    for s in students:
        grouped[(s.course, s.semester)].append(s)

    sorted_groups = sorted(grouped.keys())

    courses = sorted(list(set(s.course for s in students)))
    semesters = sorted(list(set(s.semester for s in students)))

    return tpl(
        request,
        "student_list.html",
        {
            "students": students,
            "grouped": grouped,
            "sorted_groups": sorted_groups,
            "courses": courses,
            "semesters": semesters,
        },
    )


@app.get("/admin/students/new", name="new_student")
async def new_student_get(request: Request):
    return tpl(request, "student_form.html", {"student": None})


@app.post("/admin/students/new")
async def new_student_post(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    roll_no = form.get("roll_no")
    name = form.get("name")
    gender = form.get("gender")
    dob_str = form.get("dob")
    email = form.get("email")
    contact_no = form.get("contact_no")
    course = form.get("course")
    semester = form.get("semester")

    exists = db.query(Student).get(roll_no)
    if exists:
        flash(request, "Student roll number already registered!", "error")
        return RedirectResponse(url=app.url_path_for("new_student"), status_code=303)

    dob = datetime.strptime(dob_str, "%Y-%m-%d").date() if dob_str else None

    student = Student(
        roll_no=roll_no,
        name=name,
        gender=gender,
        dob=dob,
        email=email,
        contact_no=contact_no,
        course=course,
        semester=semester,
    )
    db.add(student)
    db.commit()
    flash(request, "Student registered successfully.", "success")
    return RedirectResponse(url=app.url_path_for("view_students"), status_code=303)


@app.get("/admin/students/edit/{roll_no}", name="edit_student")
async def edit_student_get(roll_no: int, request: Request, db: Session = Depends(get_db)):
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return tpl(request, "student_form.html", {"student": student})


@app.post("/admin/students/edit/{roll_no}")
async def edit_student_post(roll_no: int, request: Request, db: Session = Depends(get_db)):
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    form = await request.form()
    student.name = form.get("name")
    student.gender = form.get("gender")
    dob_str = form.get("dob")
    student.dob = datetime.strptime(dob_str, "%Y-%m-%d").date() if dob_str else None
    student.email = form.get("email")
    student.contact_no = form.get("contact_no")
    student.course = form.get("course")
    student.semester = form.get("semester")

    db.commit()
    flash(request, "Student profile updated.", "success")
    return RedirectResponse(url=app.url_path_for("view_students"), status_code=303)


@app.post("/admin/students/delete/{roll_no}", name="delete_student")
async def delete_student(roll_no: int, request: Request, db: Session = Depends(get_db)):
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    db.delete(student)
    db.commit()
    flash(request, "Student deleted successfully.", "success")
    return RedirectResponse(url=app.url_path_for("view_students"), status_code=303)


# --- TEACHERS CRUD ---
@app.get("/admin/teachers", name="view_teachers")
async def view_teachers(request: Request, db: Session = Depends(get_db)):
    teachers = db.query(Teacher).order_by(Teacher.teacher_id).all()
    return tpl(request, "teacher_list.html", {"teachers": teachers})


@app.get("/admin/teachers/new", name="new_teacher")
async def new_teacher_get(request: Request):
    return tpl(request, "teacher_form.html", {"teacher": None})


@app.post("/admin/teachers/new")
async def new_teacher_post(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    teacher_id = form.get("teacher_id")
    name = form.get("name")
    course = form.get("course")
    password = form.get("password")

    exists = db.query(Teacher).filter_by(teacher_id=teacher_id).first()
    if exists:
        flash(request, "Teacher ID already registered!", "error")
        return RedirectResponse(url=app.url_path_for("new_teacher"), status_code=303)

    teacher = Teacher(teacher_id=teacher_id, name=name, course=course, password=password)
    db.add(teacher)
    db.commit()
    flash(request, "Teacher profile created.", "success")
    return RedirectResponse(url=app.url_path_for("view_teachers"), status_code=303)


@app.get("/admin/teachers/edit/{teacher_db_id}", name="edit_teacher")
async def edit_teacher_get(teacher_db_id: int, request: Request, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).get(teacher_db_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return tpl(request, "teacher_form.html", {"teacher": teacher})


@app.post("/admin/teachers/edit/{teacher_db_id}")
async def edit_teacher_post(teacher_db_id: int, request: Request, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).get(teacher_db_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    form = await request.form()
    teacher.name = form.get("name")
    teacher.course = form.get("course")
    password = form.get("password")
    if password:
        teacher.password = password

    db.commit()
    flash(request, "Teacher profile updated.", "success")
    return RedirectResponse(url=app.url_path_for("view_teachers"), status_code=303)


@app.post("/admin/teachers/delete/{teacher_db_id}", name="delete_teacher")
async def delete_teacher(teacher_db_id: int, request: Request, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).get(teacher_db_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    db.delete(teacher)
    db.commit()
    flash(request, "Teacher deleted successfully.", "success")
    return RedirectResponse(url=app.url_path_for("view_teachers"), status_code=303)


# --- SUBJECTS CRUD ---
@app.get("/admin/subjects", name="view_subjects")
async def view_subjects(request: Request, db: Session = Depends(get_db)):
    subjects = db.query(Subject).order_by(Subject.semester, Subject.subject_name).all()
    return tpl(request, "subject_list.html", {"subjects": subjects})


@app.get("/admin/subjects/new", name="new_subject")
async def new_subject_get(request: Request):
    return tpl(request, "subject_form.html", {"subject": None})


@app.post("/admin/subjects/new")
async def new_subject_post(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    subject_name = form.get("subject_name")
    course = form.get("course")
    semester = form.get("semester")

    subject = Subject(subject_name=subject_name, course=course, semester=semester)
    db.add(subject)
    db.commit()
    flash(request, "Subject added successfully.", "success")
    return RedirectResponse(url=app.url_path_for("view_subjects"), status_code=303)


@app.get("/admin/subjects/edit/{subject_id}", name="edit_subject")
async def edit_subject_get(subject_id: int, request: Request, db: Session = Depends(get_db)):
    subject = db.query(Subject).get(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    return tpl(request, "subject_form.html", {"subject": subject})


@app.post("/admin/subjects/edit/{subject_id}")
async def edit_subject_post(subject_id: int, request: Request, db: Session = Depends(get_db)):
    subject = db.query(Subject).get(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    form = await request.form()
    subject.subject_name = form.get("subject_name")
    subject.course = form.get("course")
    subject.semester = form.get("semester")

    db.commit()
    flash(request, "Subject details updated.", "success")
    return RedirectResponse(url=app.url_path_for("view_subjects"), status_code=303)


@app.post("/admin/subjects/delete/{subject_id}", name="delete_subject")
async def delete_subject(subject_id: int, request: Request, db: Session = Depends(get_db)):
    subject = db.query(Subject).get(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    db.delete(subject)
    db.commit()
    flash(request, "Subject deleted successfully.", "success")
    return RedirectResponse(url=app.url_path_for("view_subjects"), status_code=303)


# --- MARKS ENTRY PORTALS ---
@app.get("/marks/add", name="add_marks_portal")
async def add_marks_portal(request: Request):
    return tpl(request, "add_marks.html", {"subjects": None})


@app.post("/marks/load-subjects", name="load_subjects_for_marks")
async def load_subjects_for_marks(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    roll_no = form.get("roll_no")
    course = form.get("course")
    semester = int(form.get("semester"))

    student = db.query(Student).filter_by(roll_no=roll_no, course=course).first()
    if not student:
        flash(request, f"Student roll number {roll_no} not registered for course {course}.", "error")
        return RedirectResponse(url=app.url_path_for("add_marks_portal"), status_code=303)

    subjects = db.query(Subject).filter_by(course=course, semester=semester).all()

    if not subjects:
        flash(request, f"No subjects registered for {course} - Semester {semester}.", "error")
        return RedirectResponse(url=app.url_path_for("add_marks_portal"), status_code=303)

    return tpl(
        request,
        "add_marks.html",
        {"subjects": subjects, "roll_no": roll_no, "course": course, "semester": semester},
    )


@app.post("/marks/save", name="save_student_marks")
async def save_student_marks(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    roll_no = int(form.get("roll_no"))
    course = form.get("course")
    semester = int(form.get("semester"))

    subjects = db.query(Subject).filter_by(course=course, semester=semester).all()

    try:
        for sub in subjects:
            mark_val = int(form.get(f"marks_{sub.id}", 0))

            marks_record = db.query(Marks).filter_by(roll_no=roll_no, subject_id=sub.id).first()

            old_val = None
            action = "create"
            if marks_record:
                old_val = marks_record.marks
                action = "edit"
                marks_record.marks = mark_val
            else:
                marks_record = Marks(
                    roll_no=roll_no,
                    subject_id=sub.id,
                    marks=mark_val,
                    course=course,
                    semester=semester,
                )
                db.add(marks_record)

            if old_val != mark_val:
                log_audit(db, request, action, roll_no, sub.id, old_val, mark_val)

            if mark_val < 50:
                backlog = db.query(Backlog).filter_by(
                    roll_no=roll_no, subject_id=sub.id, status="pending"
                ).first()
                if not backlog:
                    backlog = Backlog(
                        roll_no=roll_no,
                        subject_id=sub.id,
                        semester=semester,
                        original_marks=mark_val,
                        status="pending",
                    )
                    db.add(backlog)
            else:
                backlog = db.query(Backlog).filter_by(
                    roll_no=roll_no, subject_id=sub.id, status="pending"
                ).first()
                if backlog:
                    backlog.status = "cleared"
                    backlog.cleared_marks = mark_val
                    backlog.cleared_date = datetime.utcnow()

        notify_user(db, "student", roll_no, f"New marks have been published/updated for you for Semester {semester}.")

        db.commit()
        flash(request, "Student marks successfully recorded.", "success")
    except Exception as e:
        db.rollback()
        flash(request, f"Error recording student marks: {str(e)}", "error")

    return RedirectResponse(url=app.url_path_for("add_marks_portal"), status_code=303)


# --- MARKS REPORTS & VIEWS ---
@app.get("/admin/marks-report", name="marks_report")
async def marks_report(request: Request, db: Session = Depends(get_db)):
    semester_str = request.query_params.get("semester")
    semester = int(semester_str) if semester_str else None

    report = []
    grade_distribution = {}

    if semester:
        course = request.session.get("course") if request.session.get("role") == "teacher" else None

        if course:
            students = db.query(Student).filter_by(semester=semester, course=course).all()
        else:
            students = db.query(Student).filter_by(semester=semester).all()

        subjects_query = db.query(Subject).filter_by(semester=semester)
        if course:
            subjects_query = subjects_query.filter_by(course=course)
        subjects = subjects_query.all()

        for sub in subjects:
            if course:
                marks_records = db.query(Marks).filter_by(
                    subject_id=sub.id, semester=semester, course=course
                ).all()
            else:
                marks_records = db.query(Marks).filter_by(subject_id=sub.id, semester=semester).all()

            counts = {"A": 0, "B": 0, "C": 0, "F": 0}
            for mr in marks_records:
                g = get_grade_for_percentage(db, mr.marks)
                counts[g] = counts.get(g, 0) + 1
            grade_distribution[sub.subject_name] = counts

        for s in students:
            student_marks = db.query(Marks).filter_by(roll_no=s.roll_no, semester=semester).all()

            subjects_map = {}
            for sm in student_marks:
                if sm.subject:
                    subjects_map[sm.subject.subject_name] = sm.marks

            if subjects_map:
                is_at_risk, at_risk_reason = check_at_risk(db, s)
                report.append(
                    {
                        "roll_no": s.roll_no,
                        "name": s.name,
                        "course": s.course,
                        "semester": s.semester,
                        "subjects": subjects_map,
                        "is_at_risk": is_at_risk,
                        "at_risk_reason": at_risk_reason,
                    }
                )

        report.sort(key=lambda x: x["roll_no"])

    return tpl(
        request,
        "marks_report.html",
        {"report": report, "semester": semester, "grade_distribution": grade_distribution},
    )


@app.get("/marks/edit/{roll_no}", name="edit_marks")
async def edit_marks(roll_no: int, request: Request, db: Session = Depends(get_db)):
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    marks_records = db.query(Marks).filter_by(roll_no=roll_no).all()

    if not marks_records:
        flash(request, "No marks found for this student.", "error")
        return RedirectResponse(url=app.url_path_for("marks_report"), status_code=303)

    marks = []
    for mr in marks_records:
        marks.append(
            {
                "subject_id": mr.subject_id,
                "subject_name": mr.subject.subject_name if mr.subject else "Unknown",
                "marks": mr.marks,
            }
        )

    return tpl(request, "edit_marks.html", {"roll_no": roll_no, "marks": marks})


@app.post("/marks/edit/{roll_no}", name="edit_marks_post")
async def edit_marks_post(roll_no: int, request: Request, db: Session = Depends(get_db)):
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    marks_records = db.query(Marks).filter_by(roll_no=roll_no).all()
    form = await request.form()

    try:
        for mr in marks_records:
            field_name = f"subject_{mr.subject_id}"
            new_mark = form.get(field_name)
            if new_mark is not None:
                new_mark_val = int(new_mark)
                old_val = mr.marks

                if old_val != new_mark_val:
                    mr.marks = new_mark_val
                    log_audit(db, request, "edit", roll_no, mr.subject_id, old_val, new_mark_val)

                    if new_mark_val < 50:
                        backlog = db.query(Backlog).filter_by(
                            roll_no=roll_no, subject_id=mr.subject_id, status="pending"
                        ).first()
                        if not backlog:
                            backlog = Backlog(
                                roll_no=roll_no,
                                subject_id=mr.subject_id,
                                semester=mr.semester,
                                original_marks=new_mark_val,
                                status="pending",
                            )
                            db.add(backlog)
                    else:
                        backlog = db.query(Backlog).filter_by(
                            roll_no=roll_no, subject_id=mr.subject_id, status="pending"
                        ).first()
                        if backlog:
                            backlog.status = "cleared"
                            backlog.cleared_marks = new_mark_val
                            backlog.cleared_date = datetime.utcnow()

        notify_user(db, "student", roll_no, f"Your marks have been updated for Semester {student.semester}.")

        db.commit()
        flash(request, "Student marks successfully updated.", "success")
    except Exception as e:
        db.rollback()
        flash(request, f"Error updating marks: {str(e)}", "error")

    return RedirectResponse(
        url=str(app.url_path_for("marks_report")) + f"?semester={student.semester}",
        status_code=303,
    )


@app.post("/marks/delete/{roll_no}", name="delete_marks")
async def delete_marks(roll_no: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    semester = form.get("semester")
    marks_records = db.query(Marks).filter_by(roll_no=roll_no).all()

    try:
        for mr in marks_records:
            db.delete(mr)
        db.commit()
        flash(request, "Marks deleted successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(request, f"Error deleting marks: {str(e)}", "error")

    redirect_url = str(app.url_path_for("marks_report"))
    if semester:
        redirect_url += f"?semester={semester}"
    return RedirectResponse(url=redirect_url, status_code=303)


# --- TEACHER DASHBOARD ---
@app.get("/teacher/dashboard", name="teacher_dashboard")
async def teacher_dashboard(request: Request):
    course = request.session.get("course")
    return tpl(request, "teacher_dashboard.html", {"course": course})


# --- STUDENT DASHBOARD ---
@app.get("/student/dashboard", name="student_dashboard")
async def student_dashboard(request: Request, db: Session = Depends(get_db)):
    from collections import defaultdict

    roll_no = request.session.get("roll_no")
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student_marks = db.query(Marks).filter_by(roll_no=roll_no).all()

    sem_data = defaultdict(list)
    for sm in student_marks:
        sem_data[sm.semester].append(
            {
                "subject_name": sm.subject.subject_name if sm.subject else "Unknown",
                "marks": sm.marks,
            }
        )

    sorted_sems = sorted(sem_data.keys())
    sem_stats = {}
    overall_total = 0
    overall_max = 0

    for sem in sorted_sems:
        marks = sem_data[sem]
        total = sum(m["marks"] for m in marks)
        max_possible = len(marks) * 100
        percentage = (total / max_possible * 100) if max_possible > 0 else 0

        overall_total += total
        overall_max += max_possible

        grade = get_grade_for_percentage(db, percentage)
        status = "PASS" if percentage >= 50 else "FAIL"

        rank, total_students, percentile = compute_rank(db, student.course, sem, roll_no)
        sgpa = compute_gpa(db, roll_no, sem)

        sem_stats[sem] = {
            "marks": marks,
            "total": total,
            "max_possible": max_possible,
            "percentage": round(percentage, 2),
            "grade": grade,
            "status": status,
            "rank": rank,
            "total_students": total_students,
            "percentile": percentile,
            "sgpa": sgpa,
        }

    overall_percentage = (overall_total / overall_max * 100) if overall_max > 0 else 0
    overall_grade = get_grade_for_percentage(db, overall_percentage) if overall_max > 0 else "N/A"
    overall_status = "PASS" if overall_percentage >= 50 else "FAIL" if overall_max > 0 else "N/A"

    cgpa = compute_gpa(db, roll_no)

    backlogs = (
        db.query(Backlog)
        .filter_by(roll_no=roll_no)
        .order_by(Backlog.status.desc(), Backlog.semester)
        .all()
    )

    return tpl(
        request,
        "student_dashboard.html",
        {
            "student": student,
            "sorted_sems": sorted_sems,
            "sem_stats": sem_stats,
            "overall_percentage": round(overall_percentage, 2),
            "overall_grade": overall_grade,
            "overall_status": overall_status,
            "cgpa": cgpa,
            "backlogs": backlogs,
        },
    )


# --- IN-APP NOTIFICATIONS API ---
@app.get("/api/notifications", name="get_notifications")
async def get_notifications(request: Request, db: Session = Depends(get_db)):
    if "role" not in request.session:
        return {"notifications": [], "unread_count": 0}

    role = request.session["role"]
    if role == "student":
        user_id = str(request.session["roll_no"])
    elif role == "teacher":
        user_id = request.session["teacher_id"]
    else:
        user_id = request.session["username"]

    notifications = (
        db.query(Notification)
        .filter_by(user_role=role, user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "notifications": [n.to_dict() for n in notifications],
        "unread_count": db.query(Notification)
        .filter_by(user_role=role, user_id=user_id, is_read=False)
        .count(),
    }


@app.post("/api/notifications/mark-read", name="mark_notifications_read")
async def mark_notifications_read(request: Request, db: Session = Depends(get_db)):
    if "role" not in request.session:
        return {"status": "unauthorized"}

    role = request.session["role"]
    if role == "student":
        user_id = str(request.session["roll_no"])
    elif role == "teacher":
        user_id = request.session["teacher_id"]
    else:
        user_id = request.session["username"]

    unread = db.query(Notification).filter_by(user_role=role, user_id=user_id, is_read=False).all()
    for n in unread:
        n.is_read = True
    db.commit()
    return {"status": "success"}


@app.post("/admin/notify-teacher", name="notify_teacher_post")
async def notify_teacher_post(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    teacher_id = form.get("teacher_id")
    message = form.get("message", "Correction required on marks entry.")

    teacher = db.query(Teacher).filter_by(teacher_id=teacher_id).first()
    if teacher:
        notify_user(db, "teacher", teacher_id, f"Admin requested correction: {message}")
        db.commit()
        flash(request, "Correction notification sent to teacher.", "success")
    else:
        flash(request, "Teacher not found.", "error")

    return RedirectResponse(url=app.url_path_for("view_teachers"), status_code=303)


# --- THEME TOGGLE ---
@app.get("/toggle-theme", name="toggle_theme")
async def toggle_theme(request: Request):
    current_theme = request.session.get("theme", "light")
    request.session["theme"] = "dark" if current_theme == "light" else "light"

    referer = request.headers.get("referer")
    if referer and request.url.hostname in referer:
        return RedirectResponse(url=referer, status_code=303)
    return RedirectResponse(url=app.url_path_for("home"), status_code=303)


# --- AUDIT LOGS VIEW ---
@app.get("/admin/audit-log", name="view_audit_logs")
async def view_audit_logs(request: Request, db: Session = Depends(get_db)):
    roll_no = request.query_params.get("roll_no")
    subject_id = request.query_params.get("subject_id")
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")

    query = db.query(AuditLog)

    if roll_no:
        query = query.filter(AuditLog.target_roll_no == int(roll_no))
    if subject_id:
        query = query.filter(AuditLog.subject_id == int(subject_id))
    if start_date:
        query = query.filter(AuditLog.timestamp >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.filter(
            AuditLog.timestamp <= datetime.strptime(end_date + " 23:59:59", "%Y-%m-%d %H:%M:%S")
        )

    logs = query.order_by(AuditLog.timestamp.desc()).all()
    subjects = db.query(Subject).order_by(Subject.subject_name).all()

    return tpl(
        request,
        "admin_audit_logs.html",
        {
            "logs": logs,
            "subjects": subjects,
            "roll_no": roll_no,
            "subject_id": subject_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


# --- GRADING SCHEME MANAGEMENT ---
@app.get("/admin/grading-scheme", name="manage_grading_scheme")
async def manage_grading_scheme_get(request: Request, db: Session = Depends(get_db)):
    schemes = db.query(GradingScheme).order_by(GradingScheme.min_pct.desc()).all()
    return tpl(request, "admin_grading_scheme.html", {"schemes": schemes})


@app.post("/admin/grading-scheme")
async def manage_grading_scheme_post(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    try:
        grade_letters = form.getlist("grade_letter")
        min_pcts = form.getlist("min_pct")
        max_pcts = form.getlist("max_pct")
        grade_points = form.getlist("grade_point")

        db.query(GradingScheme).delete()

        for i in range(len(grade_letters)):
            if grade_letters[i]:
                gs = GradingScheme(
                    grade_letter=grade_letters[i],
                    min_pct=float(min_pcts[i]),
                    max_pct=float(max_pcts[i]),
                    grade_point=float(grade_points[i]),
                )
                db.add(gs)
        db.commit()
        flash(request, "Grading scheme updated successfully.", "success")
    except Exception as e:
        db.rollback()
        flash(request, f"Error updating grading scheme: {str(e)}", "error")

    return RedirectResponse(url=app.url_path_for("manage_grading_scheme"), status_code=303)


# --- BACKLOGS MANAGEMENT ---
@app.get("/admin/backlogs", name="view_backlogs")
async def view_backlogs(request: Request, db: Session = Depends(get_db)):
    backlogs = db.query(Backlog).order_by(Backlog.status.desc(), Backlog.roll_no).all()
    return tpl(request, "admin_backlogs.html", {"backlogs": backlogs})


@app.post("/admin/backlogs/clear/{backlog_id}", name="clear_backlog")
async def clear_backlog(backlog_id: int, request: Request, db: Session = Depends(get_db)):
    backlog = db.query(Backlog).get(backlog_id)
    if not backlog:
        raise HTTPException(status_code=404, detail="Backlog not found")

    form = await request.form()
    cleared_marks = int(form.get("cleared_marks", 0))

    try:
        backlog.status = "cleared"
        backlog.cleared_marks = cleared_marks
        backlog.cleared_date = datetime.utcnow()

        marks_rec = db.query(Marks).filter_by(
            roll_no=backlog.roll_no, subject_id=backlog.subject_id
        ).first()
        old_val = marks_rec.marks if marks_rec else None
        if marks_rec:
            marks_rec.marks = cleared_marks
        else:
            marks_rec = Marks(
                roll_no=backlog.roll_no,
                subject_id=backlog.subject_id,
                marks=cleared_marks,
                course=backlog.student.course,
                semester=backlog.semester,
            )
            db.add(marks_rec)

        log_audit(db, request, "edit", backlog.roll_no, backlog.subject_id, old_val, cleared_marks)

        notify_user(
            db,
            "student",
            backlog.roll_no,
            f"Your backlog for subject {backlog.subject.subject_name} has been cleared with score {cleared_marks}.",
        )

        db.commit()
        flash(request, "Backlog successfully cleared.", "success")
    except Exception as e:
        db.rollback()
        flash(request, f"Error clearing backlog: {str(e)}", "error")

    return RedirectResponse(url=app.url_path_for("view_backlogs"), status_code=303)


# --- ADMIN ANALYTICS ---
@app.get("/admin/analytics", name="admin_analytics")
async def admin_analytics(request: Request, db: Session = Depends(get_db)):
    summary = get_analytics_summary(db)
    return tpl(request, "admin_analytics.html", {"summary": summary})


@app.get("/admin/analytics/export", name="export_analytics_csv")
async def export_analytics_csv(request: Request, db: Session = Depends(get_db)):
    summary = get_analytics_summary(db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Course", "Semester", "Total Students", "Average Marks", "Pass Percentage"])
    for s in summary:
        writer.writerow([s["course"], s["semester"], s["total_students"], s["avg_marks"], s["pass_percentage"]])

    content = output.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=academic_analytics.csv"},
    )


# --- SCORECARD VERIFICATION ROUTE ---
@app.get("/verify/{token}", name="verify_scorecard")
async def verify_scorecard(token: str, request: Request, db: Session = Depends(get_db)):
    verification = db.query(Verification).filter_by(token=token).first()
    if not verification:
        raise HTTPException(status_code=404, detail="Verification not found")

    student = db.query(Student).get(verification.roll_no)
    student_marks = db.query(Marks).filter_by(
        roll_no=verification.roll_no, semester=verification.semester
    ).all()
    marks_list = [
        {"subject_name": m.subject.subject_name if m.subject else "Unknown", "marks": m.marks}
        for m in student_marks
    ]

    return tpl(
        request,
        "verify_scorecard.html",
        {"verification": verification, "student": student, "marks_list": marks_list},
    )


# --- SCORECARD PDF DOWNLOAD ---
@app.get("/student/result/pdf/{roll_no}", name="download_result_pdf")
async def download_result_pdf(roll_no: int, request: Request, db: Session = Depends(get_db)):
    student = db.query(Student).get(roll_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if request.session.get("role") == "student" and request.session.get("roll_no") != roll_no:
        flash(request, "Unauthorized PDF access.", "error")
        return RedirectResponse(url=app.url_path_for("home"), status_code=303)

    semester_arg = request.query_params.get("semester")
    semester = int(semester_arg) if semester_arg else None

    if semester:
        student_marks = db.query(Marks).filter_by(roll_no=roll_no, semester=semester).all()
    else:
        student_marks = db.query(Marks).filter_by(roll_no=roll_no).all()

    marks_list = []
    for sm in student_marks:
        marks_list.append(
            {"subject_name": sm.subject.subject_name if sm.subject else "Unknown", "marks": sm.marks}
        )

    if not marks_list:
        flash(request, "No marks recorded yet, cannot generate PDF scorecard.", "error")
        if request.session.get("role") == "student":
            return RedirectResponse(url=app.url_path_for("student_dashboard"), status_code=303)
        return RedirectResponse(
            url=str(app.url_path_for("marks_report")) + f"?semester={student.semester}",
            status_code=303,
        )

    target_semester = semester if semester else student.semester

    sgpa = compute_gpa(db, roll_no, target_semester)
    cgpa = compute_gpa(db, roll_no)

    student_info = {
        "roll_no": student.roll_no,
        "name": student.name,
        "course": student.course,
        "semester": target_semester,
        "sgpa": sgpa,
        "cgpa": cgpa,
    }

    secret = "srms_super_secret_verification_key_98765"
    marks_str = ",".join(f"{m.subject_id}:{m.marks}" for m in student_marks)
    raw_str = f"{roll_no}:{target_semester}:{marks_str}:{secret}"
    hash_val = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    verification = db.query(Verification).filter_by(roll_no=roll_no, semester=target_semester).first()
    if not verification or verification.hash_val != hash_val:
        if not verification:
            token = uuid.uuid4().hex
            verification = Verification(
                token=token, roll_no=roll_no, semester=target_semester, hash_val=hash_val
            )
            db.add(verification)
        else:
            verification.hash_val = hash_val
            token = verification.token
        db.commit()
    else:
        token = verification.token

    qr_url = str(request.url_for("verify_scorecard", token=token))
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    pdf_buffer = generate_pdf(student_info, marks_list, qr_image_buffer=qr_buffer)
    suffix = f"_Sem{target_semester}" if semester else ""

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Result_{roll_no}{suffix}.pdf"},
    )


# ─── DATABASE SEED UTILITY ──────────────────────────────────────────

def seed_database():
    """Seed the database with initial data if empty."""
    db = SessionLocal()
    try:
        # 1. Seed system settings
        if not db.query(SystemSetting).filter_by(key="at_risk_threshold").first():
            db.add(SystemSetting(key="at_risk_threshold", value="55.0"))

        # 2. Seed grading scheme
        if not db.query(GradingScheme).first():
            schemes = [
                GradingScheme(grade_letter="A", min_pct=75.0, max_pct=100.0, grade_point=10.0),
                GradingScheme(grade_letter="B", min_pct=60.0, max_pct=74.99, grade_point=8.0),
                GradingScheme(grade_letter="C", min_pct=50.0, max_pct=59.99, grade_point=6.0),
                GradingScheme(grade_letter="F", min_pct=0.0, max_pct=49.99, grade_point=0.0),
            ]
            db.add_all(schemes)
            db.commit()

        # Check if Admin table is empty
        if not db.query(Admin).first():
            print("Seeding database with mock records...")
            import random

            admin = Admin(username="admin", password="admin123")
            db.add(admin)

            teachers = [
                Teacher(teacher_id="T101", name="Jane Smith", course="BCA", password="teacher123"),
                Teacher(teacher_id="T102", name="John Doe", course="B.Tech", password="teacher123"),
                Teacher(teacher_id="T103", name="Sarah Connor", course="BA", password="teacher123"),
            ]
            db.add_all(teachers)

            subjects_data = {
                ("BCA", 1): ["C Programming", "Principles of Management", "Business Communication"],
                ("BCA", 2): ["Data Structures", "Discrete Mathematics", "Database Systems"],
                ("BCA", 3): ["Java Programming", "Operating Systems", "Computer Networks"],
                ("BCA", 4): ["Web Technologies", "Software Engineering", "Python Development"],
                ("BCA", 5): ["Linux Administration", "PHP & MySQL", "Cloud Computing"],
                ("BCA", 6): ["Artificial Intelligence", "Cyber Security", "Major Project"],
                ("B.Tech", 1): ["Engineering Mathematics I", "Engineering Physics", "Programming in C"],
                ("B.Tech", 2): ["Engineering Mathematics II", "Engineering Chemistry", "Data Structures"],
                ("B.Tech", 3): [
                    "Object Oriented Programming",
                    "Digital Logic Design",
                    "Discrete Structures",
                ],
                ("B.Tech", 4): [
                    "Database Management Systems",
                    "Theory of Computation",
                    "Computer Architecture",
                ],
                ("B.Tech", 5): [
                    "Design and Analysis of Algorithms",
                    "Operating Systems",
                    "Software Engineering",
                ],
                ("B.Tech", 6): ["Computer Networks", "Compiler Design", "Web Engineering"],
                ("B.Tech", 7): [
                    "Cryptography & Network Security",
                    "Cloud Computing",
                    "Distributed Systems",
                ],
                ("B.Tech", 8): ["Machine Learning", "Major Project", "Seminar"],
                ("BA", 1): ["Introduction to Sociology", "Micro Economics", "English Literature I"],
                ("BA", 2): ["Social Psychology", "Macro Economics", "English Literature II"],
                ("BA", 3): ["Political Science I", "History of India I", "Environmental Studies"],
                ("BA", 4): ["Political Science II", "History of India II", "Public Administration"],
                ("BA", 5): ["International Relations", "Indian Economy", "Human Rights"],
                ("BA", 6): ["Global Politics", "Social Philosophy", "Research Methodology"],
            }

            added_subjects = []
            for (course, sem), sub_list in subjects_data.items():
                for name in sub_list:
                    credits_val = random.choice([3, 4])
                    sub = Subject(subject_name=name, course=course, semester=sem, credits=credits_val)
                    db.add(sub)
                    added_subjects.append(sub)

            db.flush()

            student_names = [
                "Ethan Hunt", "Clara Oswald", "David Tennant", "Rose Tyler", "Martha Jones",
                "Donna Noble", "Peter Parker", "Bruce Wayne", "Clark Kent", "Diana Prince",
                "Barry Allen", "Hal Jordan", "Arthur Curry", "Victor Stone", "Wanda Maximoff",
                "Steve Rogers", "Tony Stark", "Bruce Banner", "Natasha Romanoff", "Clint Barton",
                "Thor Odinson", "Loki Laufeyson", "Stephen Strange", "Peter Quill", "Gamora Zen",
                "Groot", "Rocket Raccoon", "Drax Destroyer", "Mantis", "Nebula", "Wade Wilson",
                "Logan Howlett", "Charles Xavier", "Jean Grey", "Scott Summers", "Ororo Munroe",
                "Bobby Drake", "Hank McCoy", "Remy LeBeau", "Anna Marie", "Kurt Wagner",
            ]

            student_idx = 0
            roll_no_counter = 5001

            courses_sems = [("BCA", 6), ("B.Tech", 8), ("BA", 6)]

            for course, max_sem in courses_sems:
                for sem in range(1, max_sem + 1):
                    for s_num in range(1, 3):
                        name = student_names[student_idx % len(student_names)]
                        display_name = f"{name} ({course} S{sem})"
                        gender = "Male" if student_idx % 2 == 0 else "Female"
                        dob = datetime.strptime("2005-05-15", "%Y-%m-%d").date()
                        email = f"{name.lower().replace(' ', '')}@example.com"
                        contact_no = f"98765432{student_idx:02d}"

                        student = Student(
                            roll_no=roll_no_counter,
                            name=display_name,
                            gender=gender,
                            dob=dob,
                            email=email,
                            contact_no=contact_no,
                            course=course,
                            semester=sem,
                        )
                        db.add(student)

                        for prev_sem in range(1, sem + 1):
                            subjects_for_term = [
                                sub
                                for sub in added_subjects
                                if sub.course == course and sub.semester == prev_sem
                            ]
                            for sub in subjects_for_term:
                                if random.random() < 0.10:
                                    marks_val = random.randint(35, 48)
                                else:
                                    marks_val = random.randint(52, 98)

                                marks_rec = Marks(
                                    roll_no=roll_no_counter,
                                    subject_id=sub.id,
                                    marks=marks_val,
                                    course=course,
                                    semester=prev_sem,
                                )
                                db.add(marks_rec)

                                # Audit log for seeding
                                audit = AuditLog(
                                    actor_role="system",
                                    actor_id="system",
                                    action="create",
                                    target_roll_no=roll_no_counter,
                                    subject_id=sub.id,
                                    old_value=None,
                                    new_value=marks_val,
                                )
                                db.add(audit)

                                if marks_val < 50:
                                    backlog = Backlog(
                                        roll_no=roll_no_counter,
                                        subject_id=sub.id,
                                        semester=prev_sem,
                                        original_marks=marks_val,
                                        status="pending",
                                    )
                                    db.add(backlog)

                        notify_user(
                            db,
                            "student",
                            roll_no_counter,
                            f"Welcome to the portal. Semester {sem} grades are published.",
                        )

                        roll_no_counter += 1
                        student_idx += 1

            db.commit()
            print("Database seeding completed.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    seed_database()
    uvicorn.run(app, host="0.0.0.0", port=5000)
