
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from config import Config
from database import db
from models import Admin, Student, Teacher, Subject, Marks, GradingScheme, Backlog, Notification, AuditLog, Verification, SystemSetting
from utils.pdf_generator import generate_pdf
from datetime import datetime
from functools import wraps
import hashlib
import uuid
import qrcode
import io
import csv

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

# Schema migrator for credits column in subjects table
def check_and_add_credits_column():
    try:
        inspector = db.inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('subjects')]
        if 'credits' not in columns:
            print("Altering table subjects to add credits column...")
            db.session.execute(db.text("ALTER TABLE subjects ADD COLUMN credits INTEGER DEFAULT 3 NOT NULL"))
            db.session.commit()
    except Exception as e:
        print(f"Credits column migration check failed: {e}")

# Helper: get grade letter for a percentage/score
def get_grade_for_percentage(percentage):
    try:
        schemes = GradingScheme.query.order_by(GradingScheme.min_pct.desc()).all()
        for s in schemes:
            if s.min_pct <= percentage <= s.max_pct:
                return s.grade_letter
    except Exception:
        pass
    if percentage >= 75: return 'A'
    elif percentage >= 60: return 'B'
    elif percentage >= 50: return 'C'
    return 'F'

# Helper: get grade point for a score
def get_gp_for_score(percentage):
    try:
        schemes = GradingScheme.query.order_by(GradingScheme.min_pct.desc()).all()
        for s in schemes:
            if s.min_pct <= percentage <= s.max_pct:
                return s.grade_point
    except Exception:
        pass
    if percentage >= 75: return 10.0
    elif percentage >= 60: return 8.0
    elif percentage >= 50: return 6.0
    return 0.0

# Helper: compute SGPA (for a semester) or CGPA (overall)
def compute_gpa(roll_no, semester=None):
    query = Marks.query.filter_by(roll_no=roll_no)
    if semester:
        query = query.filter_by(semester=semester)
    marks_records = query.all()
    
    total_credit_points = 0.0
    total_credits = 0
    
    for mr in marks_records:
        sub = mr.subject
        if sub:
            credits = sub.credits or 3
            gp = get_gp_for_score(mr.marks)
            total_credit_points += gp * credits
            total_credits += credits
            
    if total_credits == 0:
        return 0.0
    return round(total_credit_points / total_credits, 2)

# Helper: compute Class Rank and Percentile
def compute_rank(course, semester, roll_no):
    all_students_in_course = Student.query.filter_by(course=course).all()
    student_rolls = [s.roll_no for s in all_students_in_course]
    all_marks = Marks.query.filter_by(course=course, semester=semester).all()
    
    from collections import defaultdict
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

# Helper: check at-risk students
def check_at_risk(student):
    student_marks = Marks.query.filter_by(roll_no=student.roll_no).all()
    from collections import defaultdict
    sem_data = defaultdict(list)
    for sm in student_marks:
        sem_data[sm.semester].append(sm.marks)
        
    sorted_sems = sorted(sem_data.keys())
    sem_percentages = []
    for sem in sorted_sems:
        marks = sem_data[sem]
        pct = sum(marks) / len(marks) if marks else 0
        sem_percentages.append((sem, pct))
        
    threshold_setting = SystemSetting.query.filter_by(key='at_risk_threshold').first()
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

# Helper: log audit entries
def log_audit(action, target_roll_no, subject_id, old_value, new_value):
    try:
        log = AuditLog(
            actor_role=session.get('role', 'system'),
            actor_id=session.get('username', 'system'),
            action=action,
            target_roll_no=target_roll_no,
            subject_id=subject_id,
            old_value=old_value,
            new_value=new_value
        )
        db.session.add(log)
    except Exception as e:
        print(f"Error logging audit entry: {e}")

# Helper: notify user
def notify_user(user_role, user_id, message):
    try:
        notif = Notification(
            user_role=user_role,
            user_id=str(user_id),
            message=message
        )
        db.session.add(notif)
    except Exception as e:
        print(f"Error creating notification: {e}")

# Session login checker decorator
def login_required(roles=None):
    if roles is None:
        roles = []
    if isinstance(roles, str):
        roles = [roles]
        
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session:
                flash('Please sign in to access this page.', 'error')
                return redirect(url_for('home'))
            if roles and session.get('role') not in roles:
                flash('Unauthorized access privileges.', 'error')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- PORTAL HOMEPAGE ---
@app.route('/')
def home():
    if 'role' in session:
        role = session['role']
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        elif role == 'student':
            return redirect(url_for('student_dashboard'))
    return render_template('index.html')

# --- LOGINS & AUTHENTICATION ---
@app.route('/login/<role>')
def login(role):
    if role not in ['admin', 'teacher', 'student']:
        return redirect(url_for('home'))
    return render_template('login.html', role=role)

@app.route('/login/<role>', methods=['POST'])
def login_post(role):
    if role == 'admin':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Admin.query.filter_by(username=username, password=password).first()
        if admin:
            session['role'] = 'admin'
            session['username'] = admin.username
            flash('Admin successfully logged in.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid Admin Credentials.', 'error')
            
    elif role == 'teacher':
        teacher_id = request.form.get('teacher_id')
        password = request.form.get('password')
        teacher = Teacher.query.filter_by(teacher_id=teacher_id, password=password).first()
        if teacher:
            session['role'] = 'teacher'
            session['teacher_db_id'] = teacher.id
            session['username'] = teacher.name
            session['teacher_id'] = teacher.teacher_id
            session['course'] = teacher.course
            flash(f'Welcome, Prof. {teacher.name}', 'success')
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid Teacher ID or Password.', 'error')
            
    elif role == 'student':
        roll_no = request.form.get('roll_no')
        password = request.form.get('password')
        
        student = Student.query.filter_by(roll_no=roll_no).first()
        if student:
            # Format DOB as 8 digits (DDMMYYYY and YYYYMMDD)
            dob_ddmmyyyy = student.dob.strftime('%d%m%Y') if student.dob else ""
            dob_yyyymmdd = student.dob.strftime('%Y%m%d') if student.dob else ""
            
            if password in [dob_ddmmyyyy, dob_yyyymmdd]:
                session['role'] = 'student'
                session['roll_no'] = student.roll_no
                session['username'] = student.name
                flash(f'Welcome, {student.name}', 'success')
                return redirect(url_for('student_dashboard'))
            else:
                flash('Invalid Date of Birth. Use format DDMMYYYY (e.g. 15052004).', 'error')
        else:
            flash('No student profile found for this roll number.', 'error')
            
    return redirect(url_for('login', role=role))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home'))


# --- ADMIN VIEWS ---
@app.route('/admin/dashboard')
@login_required('admin')
def admin_dashboard():
    # Gather counts
    student_count = Student.query.count()
    teacher_count = Teacher.query.count()
    subject_count = Subject.query.count()
    stats = {
        'students': student_count,
        'teachers': teacher_count,
        'subjects': subject_count
    }
    return render_template('admin_dashboard.html', stats=stats)


# --- STUDENTS CRUD ---
@app.route('/admin/students')
@login_required('admin')
def view_students():
    students = Student.query.order_by(Student.roll_no).all()
    
    for s in students:
        is_at_risk, reason = check_at_risk(s)
        s.is_at_risk = is_at_risk
        s.at_risk_reason = reason
        
    # Group students by (course, semester)
    from collections import defaultdict
    grouped = defaultdict(list)
    for s in students:
        grouped[(s.course, s.semester)].append(s)
        
    # Sort the groups by course, then semester
    sorted_groups = sorted(grouped.keys())
    
    # Get all unique courses and semesters for filters
    courses = sorted(list(set(s.course for s in students)))
    semesters = sorted(list(set(s.semester for s in students)))
    
    return render_template(
        'student_list.html',
        students=students,
        grouped=grouped,
        sorted_groups=sorted_groups,
        courses=courses,
        semesters=semesters
    )

@app.route('/admin/students/new', methods=['GET', 'POST'])
@login_required('admin')
def new_student():
    if request.method == 'POST':
        roll_no = request.form.get('roll_no')
        name = request.form.get('name')
        gender = request.form.get('gender')
        dob_str = request.form.get('dob')
        email = request.form.get('email')
        contact_no = request.form.get('contact_no')
        course = request.form.get('course')
        semester = request.form.get('semester')
        
        # Check if roll no exists
        exists = Student.query.get(roll_no)
        if exists:
            flash('Student roll number already registered!', 'error')
            return redirect(url_for('new_student'))
            
        dob = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        
        student = Student(
            roll_no=roll_no, name=name, gender=gender, dob=dob,
            email=email, contact_no=contact_no, course=course, semester=semester
        )
        db.session.add(student)
        db.session.commit()
        flash('Student registered successfully.', 'success')
        return redirect(url_for('view_students'))
        
    return render_template('student_form.html', student=None)

@app.route('/admin/students/edit/<int:roll_no>', methods=['GET', 'POST'])
@login_required('admin')
def edit_student(roll_no):
    student = Student.query.get_or_404(roll_no)
    if request.method == 'POST':
        student.name = request.form.get('name')
        student.gender = request.form.get('gender')
        dob_str = request.form.get('dob')
        student.dob = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        student.email = request.form.get('email')
        student.contact_no = request.form.get('contact_no')
        student.course = request.form.get('course')
        student.semester = request.form.get('semester')
        
        db.session.commit()
        flash('Student profile updated.', 'success')
        return redirect(url_for('view_students'))
        
    return render_template('student_form.html', student=student)

@app.route('/admin/students/delete/<int:roll_no>', methods=['POST'])
@login_required('admin')
def delete_student(roll_no):
    student = Student.query.get_or_404(roll_no)
    db.session.delete(student)
    db.session.commit()
    flash('Student deleted successfully.', 'success')
    return redirect(url_for('view_students'))


# --- TEACHERS CRUD ---
@app.route('/admin/teachers')
@login_required('admin')
def view_teachers():
    teachers = Teacher.query.order_by(Teacher.teacher_id).all()
    return render_template('teacher_list.html', teachers=teachers)

@app.route('/admin/teachers/new', methods=['GET', 'POST'])
@login_required('admin')
def new_teacher():
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')
        name = request.form.get('name')
        course = request.form.get('course')
        password = request.form.get('password')
        
        exists = Teacher.query.filter_by(teacher_id=teacher_id).first()
        if exists:
            flash('Teacher ID already registered!', 'error')
            return redirect(url_for('new_teacher'))
            
        teacher = Teacher(teacher_id=teacher_id, name=name, course=course, password=password)
        db.session.add(teacher)
        db.session.commit()
        flash('Teacher profile created.', 'success')
        return redirect(url_for('view_teachers'))
        
    return render_template('teacher_form.html', teacher=None)

@app.route('/admin/teachers/edit/<int:teacher_db_id>', methods=['GET', 'POST'])
@login_required('admin')
def edit_teacher(teacher_db_id):
    teacher = Teacher.query.get_or_404(teacher_db_id)
    if request.method == 'POST':
        teacher.name = request.form.get('name')
        teacher.course = request.form.get('course')
        
        password = request.form.get('password')
        if password:  # If password field is filled
            teacher.password = password
            
        db.session.commit()
        flash('Teacher profile updated.', 'success')
        return redirect(url_for('view_teachers'))
        
    return render_template('teacher_form.html', teacher=teacher)

@app.route('/admin/teachers/delete/<int:teacher_db_id>', methods=['POST'])
@login_required('admin')
def delete_teacher(teacher_db_id):
    teacher = Teacher.query.get_or_404(teacher_db_id)
    db.session.delete(teacher)
    db.session.commit()
    flash('Teacher deleted successfully.', 'success')
    return redirect(url_for('view_teachers'))


# --- SUBJECTS CRUD ---
@app.route('/admin/subjects')
@login_required('admin')
def view_subjects():
    subjects = Subject.query.order_by(Subject.semester, Subject.subject_name).all()
    return render_template('subject_list.html', subjects=subjects)

@app.route('/admin/subjects/new', methods=['GET', 'POST'])
@login_required('admin')
def new_subject():
    if request.method == 'POST':
        subject_name = request.form.get('subject_name')
        course = request.form.get('course')
        semester = request.form.get('semester')
        
        subject = Subject(subject_name=subject_name, course=course, semester=semester)
        db.session.add(subject)
        db.session.commit()
        flash('Subject added successfully.', 'success')
        return redirect(url_for('view_subjects'))
        
    return render_template('subject_form.html', subject=None)

@app.route('/admin/subjects/edit/<int:subject_id>', methods=['GET', 'POST'])
@login_required('admin')
def edit_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    if request.method == 'POST':
        subject.subject_name = request.form.get('subject_name')
        subject.course = request.form.get('course')
        subject.semester = request.form.get('semester')
        
        db.session.commit()
        flash('Subject details updated.', 'success')
        return redirect(url_for('view_subjects'))
        
    return render_template('subject_form.html', subject=subject)

@app.route('/admin/subjects/delete/<int:subject_id>', methods=['POST'])
@login_required('admin')
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    flash('Subject deleted successfully.', 'success')
    return redirect(url_for('view_subjects'))


# --- MARKS ENTRY PORTALS ---
@app.route('/marks/add')
@login_required(['admin', 'teacher'])
def add_marks_portal():
    return render_template('add_marks.html', subjects=None)

@app.route('/marks/load-subjects', methods=['POST'])
@login_required(['admin', 'teacher'])
def load_subjects_for_marks():
    roll_no = request.form.get('roll_no')
    course = request.form.get('course')
    semester = int(request.form.get('semester'))
    
    # Check if student exists
    student = Student.query.filter_by(roll_no=roll_no, course=course).first()
    if not student:
        flash(f'Student roll number {roll_no} not registered for course {course}.', 'error')
        return redirect(url_for('add_marks_portal'))
        
    # Get subjects for that course and semester
    subjects = Subject.query.filter_by(course=course, semester=semester).all()
    
    if not subjects:
        flash(f'No subjects registered for {course} - Semester {semester}.', 'error')
        return redirect(url_for('add_marks_portal'))
        
    return render_template('add_marks.html', subjects=subjects, roll_no=roll_no, course=course, semester=semester)

@app.route('/marks/save', methods=['POST'])
@login_required(['admin', 'teacher'])
def save_student_marks():
    roll_no = int(request.form.get('roll_no'))
    course = request.form.get('course')
    semester = int(request.form.get('semester'))
    
    subjects = Subject.query.filter_by(course=course, semester=semester).all()
    
    try:
        for sub in subjects:
            mark_val = int(request.form.get(f'marks_{sub.id}', 0))
            
            # Check if marks already registered
            marks_record = Marks.query.filter_by(roll_no=roll_no, subject_id=sub.id).first()
            
            old_val = None
            action = 'create'
            if marks_record:
                old_val = marks_record.marks
                action = 'edit'
                marks_record.marks = mark_val
            else:
                marks_record = Marks(
                    roll_no=roll_no, subject_id=sub.id, marks=mark_val,
                    course=course, semester=semester
                )
                db.session.add(marks_record)
                
            # Log Audit if value changed
            if old_val != mark_val:
                log_audit(action, roll_no, sub.id, old_val, mark_val)
                
            # Manage Backlog if marks < 50
            if mark_val < 50:
                backlog = Backlog.query.filter_by(roll_no=roll_no, subject_id=sub.id, status='pending').first()
                if not backlog:
                    backlog = Backlog(
                        roll_no=roll_no,
                        subject_id=sub.id,
                        semester=semester,
                        original_marks=mark_val,
                        status='pending'
                    )
                    db.session.add(backlog)
            else:
                # If they passed now, clear any pending backlog for this subject
                backlog = Backlog.query.filter_by(roll_no=roll_no, subject_id=sub.id, status='pending').first()
                if backlog:
                    backlog.status = 'cleared'
                    backlog.cleared_marks = mark_val
                    backlog.cleared_date = datetime.utcnow()
                    
        # Notify student about updated marks
        notify_user('student', roll_no, f"New marks have been published/updated for you for Semester {semester}.")
        
        db.session.commit()
        flash('Student marks successfully recorded.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error recording student marks: {str(e)}', 'error')
        
    return redirect(url_for('add_marks_portal'))


# --- MARKS REPORTS & VIEWS ---
@app.route('/admin/marks-report')
@login_required(['admin', 'teacher'])
def marks_report():
    semester_str = request.args.get('semester')
    semester = int(semester_str) if semester_str else None
    
    report = []
    grade_distribution = {}
    
    if semester:
        course = session.get('course') if session.get('role') == 'teacher' else None
        
        # Get students matching the semester
        if course:
            students = Student.query.filter_by(semester=semester, course=course).all()
        else:
            students = Student.query.filter_by(semester=semester).all()
            
        # Get subjects for the semester
        subjects_query = Subject.query.filter_by(semester=semester)
        if course:
            subjects_query = subjects_query.filter_by(course=course)
        subjects = subjects_query.all()
        
        # Compute grade distribution for each subject
        for sub in subjects:
            if course:
                marks_records = Marks.query.filter_by(subject_id=sub.id, semester=semester, course=course).all()
            else:
                marks_records = Marks.query.filter_by(subject_id=sub.id, semester=semester).all()
                
            counts = {'A': 0, 'B': 0, 'C': 0, 'F': 0}
            for mr in marks_records:
                g = get_grade_for_percentage(mr.marks)
                if g in counts:
                    counts[g] += 1
                else:
                    counts[g] = counts.get(g, 0) + 1
            grade_distribution[sub.subject_name] = counts
            
        for s in students:
            # Fetch marks for student
            student_marks = Marks.query.filter_by(roll_no=s.roll_no, semester=semester).all()
            
            # Construct a map of subjects -> marks
            subjects_map = {}
            for sm in student_marks:
                if sm.subject:
                    subjects_map[sm.subject.subject_name] = sm.marks
                    
            if subjects_map: # Only include if they have marks recorded
                # Check if at risk
                is_at_risk, at_risk_reason = check_at_risk(s)
                
                report.append({
                    'roll_no': s.roll_no,
                    'name': s.name,
                    'course': s.course,
                    'semester': s.semester,
                    'subjects': subjects_map,
                    'is_at_risk': is_at_risk,
                    'at_risk_reason': at_risk_reason
                })
                
        # Sort report by roll number
        report.sort(key=lambda x: x['roll_no'])
        
    return render_template('marks_report.html', report=report, semester=semester, grade_distribution=grade_distribution)

@app.route('/marks/edit/<int:roll_no>')
@login_required(['admin', 'teacher'])
def edit_marks(roll_no):
    student = Student.query.get_or_404(roll_no)
    
    # Retrieve marks joined with subjects
    marks_records = Marks.query.filter_by(roll_no=roll_no).all()
    
    if not marks_records:
        flash('No marks found for this student.', 'error')
        return redirect(url_for('marks_report'))
        
    marks = []
    for mr in marks_records:
        marks.append({
            'subject_id': mr.subject_id,
            'subject_name': mr.subject.subject_name if mr.subject else 'Unknown',
            'marks': mr.marks
        })
        
    return render_template('edit_marks.html', roll_no=roll_no, marks=marks)

@app.route('/marks/edit/<int:roll_no>', methods=['POST'])
@login_required(['admin', 'teacher'])
def edit_marks_post(roll_no):
    student = Student.query.get_or_404(roll_no)
    marks_records = Marks.query.filter_by(roll_no=roll_no).all()
    
    try:
        for mr in marks_records:
            field_name = f'subject_{mr.subject_id}'
            new_mark = request.form.get(field_name)
            if new_mark is not None:
                new_mark_val = int(new_mark)
                old_val = mr.marks
                
                if old_val != new_mark_val:
                    mr.marks = new_mark_val
                    log_audit('edit', roll_no, mr.subject_id, old_val, new_mark_val)
                    
                    # Backlog management
                    if new_mark_val < 50:
                        backlog = Backlog.query.filter_by(roll_no=roll_no, subject_id=mr.subject_id, status='pending').first()
                        if not backlog:
                            backlog = Backlog(
                                roll_no=roll_no,
                                subject_id=mr.subject_id,
                                semester=mr.semester,
                                original_marks=new_mark_val,
                                status='pending'
                            )
                            db.session.add(backlog)
                    else:
                        backlog = Backlog.query.filter_by(roll_no=roll_no, subject_id=mr.subject_id, status='pending').first()
                        if backlog:
                            backlog.status = 'cleared'
                            backlog.cleared_marks = new_mark_val
                            backlog.cleared_date = datetime.utcnow()
                            
        # Notify student
        notify_user('student', roll_no, f"Your marks have been updated for Semester {student.semester}.")
        
        db.session.commit()
        flash('Student marks successfully updated.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating marks: {str(e)}', 'error')
        
    return redirect(url_for('marks_report', semester=student.semester))

@app.route('/marks/delete/<int:roll_no>', methods=['POST'])
@login_required(['admin', 'teacher'])
def delete_marks(roll_no):
    semester = request.form.get('semester')
    marks_records = Marks.query.filter_by(roll_no=roll_no).all()
    
    try:
        for mr in marks_records:
            db.session.delete(mr)
        db.session.commit()
        flash('Marks deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting marks: {str(e)}', 'error')
        
    return redirect(url_for('marks_report', semester=semester))


# --- TEACHER DASHBOARD ---
@app.route('/teacher/dashboard')
@login_required('teacher')
def teacher_dashboard():
    course = session.get('course')
    return render_template('teacher_dashboard.html', course=course)


# --- STUDENT DASHBOARD ---
@app.route('/student/dashboard')
@login_required('student')
def student_dashboard():
    roll_no = session.get('roll_no')
    student = Student.query.get_or_404(roll_no)
    
    # Fetch student marks
    student_marks = Marks.query.filter_by(roll_no=roll_no).all()
    
    from collections import defaultdict
    sem_data = defaultdict(list)
    for sm in student_marks:
        sem_data[sm.semester].append({
            'subject_name': sm.subject.subject_name if sm.subject else 'Unknown',
            'marks': sm.marks
        })
        
    sorted_sems = sorted(sem_data.keys())
    sem_stats = {}
    overall_total = 0
    overall_max = 0
    
    for sem in sorted_sems:
        marks = sem_data[sem]
        total = sum(m['marks'] for m in marks)
        max_possible = len(marks) * 100
        percentage = (total / max_possible * 100) if max_possible > 0 else 0
        
        overall_total += total
        overall_max += max_possible
        
        grade = get_grade_for_percentage(percentage)
        status = "PASS" if percentage >= 50 else "FAIL"
        
        # Calculate rank & percentile
        rank, total_students, percentile = compute_rank(student.course, sem, roll_no)
        
        # Calculate SGPA
        sgpa = compute_gpa(roll_no, sem)
        
        sem_stats[sem] = {
            'marks': marks,
            'total': total,
            'max_possible': max_possible,
            'percentage': round(percentage, 2),
            'grade': grade,
            'status': status,
            'rank': rank,
            'total_students': total_students,
            'percentile': percentile,
            'sgpa': sgpa
        }
        
    overall_percentage = (overall_total / overall_max * 100) if overall_max > 0 else 0
    overall_grade = get_grade_for_percentage(overall_percentage) if overall_max > 0 else "N/A"
    overall_status = "PASS" if overall_percentage >= 50 else "FAIL" if overall_max > 0 else "N/A"
    
    # CGPA calculation
    cgpa = compute_gpa(roll_no)
    
    # Fetch backlogs
    backlogs = Backlog.query.filter_by(roll_no=roll_no).order_by(Backlog.status.desc(), Backlog.semester).all()
    
    return render_template(
        'student_dashboard.html', 
        student=student, 
        sorted_sems=sorted_sems,
        sem_stats=sem_stats,
        overall_percentage=round(overall_percentage, 2),
        overall_grade=overall_grade,
        overall_status=overall_status,
        cgpa=cgpa,
        backlogs=backlogs
    )


# --- IN-APP NOTIFICATIONS API ---
@app.route('/api/notifications')
def get_notifications():
    if 'role' not in session:
        return {'notifications': []}, 401
    
    role = session['role']
    if role == 'student':
        user_id = str(session['roll_no'])
    elif role == 'teacher':
        user_id = session['teacher_id']
    else:
        user_id = session['username']
        
    notifications = Notification.query.filter_by(user_role=role, user_id=user_id)\
                                       .order_by(Notification.created_at.desc()).limit(10).all()
    return {
        'notifications': [n.to_dict() for n in notifications],
        'unread_count': Notification.query.filter_by(user_role=role, user_id=user_id, is_read=False).count()
    }

@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    if 'role' not in session:
        return {'status': 'unauthorized'}, 401
    
    role = session['role']
    if role == 'student':
        user_id = str(session['roll_no'])
    elif role == 'teacher':
        user_id = session['teacher_id']
    else:
        user_id = session['username']
        
    unread = Notification.query.filter_by(user_role=role, user_id=user_id, is_read=False).all()
    for n in unread:
        n.is_read = True
    db.session.commit()
    return {'status': 'success'}

@app.route('/admin/notify-teacher', methods=['POST'])
@login_required('admin')
def notify_teacher_post():
    teacher_id = request.form.get('teacher_id')
    message = request.form.get('message', 'Correction required on marks entry.')
    
    teacher = Teacher.query.filter_by(teacher_id=teacher_id).first()
    if teacher:
        notify_user('teacher', teacher_id, f"Admin requested correction: {message}")
        db.session.commit()
        flash('Correction notification sent to teacher.', 'success')
    else:
        flash('Teacher not found.', 'error')
        
    return redirect(url_for('view_teachers'))

# --- THEME TOGGLE ---
@app.route('/toggle-theme')
def toggle_theme():
    current_theme = session.get('theme', 'light')
    session['theme'] = 'dark' if current_theme == 'light' else 'light'
    
    ref = request.referrer
    if ref and request.host in ref:
        return redirect(ref)
    return redirect(url_for('home'))

# --- AUDIT LOGS VIEW ---
@app.route('/admin/audit-log')
@login_required('admin')
def view_audit_logs():
    roll_no = request.args.get('roll_no')
    subject_id = request.args.get('subject_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = AuditLog.query
    
    if roll_no:
        query = query.filter(AuditLog.target_roll_no == int(roll_no))
    if subject_id:
        query = query.filter(AuditLog.subject_id == int(subject_id))
    if start_date:
        query = query.filter(AuditLog.timestamp >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(AuditLog.timestamp <= datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        
    logs = query.order_by(AuditLog.timestamp.desc()).all()
    subjects = Subject.query.order_by(Subject.subject_name).all()
    
    return render_template(
        'admin_audit_logs.html',
        logs=logs,
        subjects=subjects,
        roll_no=roll_no,
        subject_id=subject_id,
        start_date=start_date,
        end_date=end_date
    )

# --- GRADING SCHEME MANAGEMENT ---
@app.route('/admin/grading-scheme', methods=['GET', 'POST'])
@login_required('admin')
def manage_grading_scheme():
    if request.method == 'POST':
        try:
            ids = request.form.getlist('id')
            grade_letters = request.form.getlist('grade_letter')
            min_pcts = request.form.getlist('min_pct')
            max_pcts = request.form.getlist('max_pct')
            grade_points = request.form.getlist('grade_point')
            
            GradingScheme.query.delete()
            
            for i in range(len(grade_letters)):
                if grade_letters[i]:
                    gs = GradingScheme(
                        grade_letter=grade_letters[i],
                        min_pct=float(min_pcts[i]),
                        max_pct=float(max_pcts[i]),
                        grade_point=float(grade_points[i])
                    )
                    db.session.add(gs)
            db.session.commit()
            flash('Grading scheme updated successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating grading scheme: {str(e)}', 'error')
            
        return redirect(url_for('manage_grading_scheme'))
        
    schemes = GradingScheme.query.order_by(GradingScheme.min_pct.desc()).all()
    return render_template('admin_grading_scheme.html', schemes=schemes)

# --- BACKLOGS MANAGEMENT ---
@app.route('/admin/backlogs')
@login_required('admin')
def view_backlogs():
    backlogs = Backlog.query.order_by(Backlog.status.desc(), Backlog.roll_no).all()
    return render_template('admin_backlogs.html', backlogs=backlogs)

@app.route('/admin/backlogs/clear/<int:backlog_id>', methods=['POST'])
@login_required('admin')
def clear_backlog(backlog_id):
    backlog = Backlog.query.get_or_404(backlog_id)
    cleared_marks = int(request.form.get('cleared_marks', 0))
    
    try:
        backlog.status = 'cleared'
        backlog.cleared_marks = cleared_marks
        backlog.cleared_date = datetime.utcnow()
        
        # Update Marks table
        marks_rec = Marks.query.filter_by(roll_no=backlog.roll_no, subject_id=backlog.subject_id).first()
        old_val = marks_rec.marks if marks_rec else None
        if marks_rec:
            marks_rec.marks = cleared_marks
        else:
            marks_rec = Marks(
                roll_no=backlog.roll_no,
                subject_id=backlog.subject_id,
                marks=cleared_marks,
                course=backlog.student.course,
                semester=backlog.semester
            )
            db.session.add(marks_rec)
            
        # Log Audit
        log_audit('edit', backlog.roll_no, backlog.subject_id, old_val, cleared_marks)
        
        # Notify student
        notify_user('student', backlog.roll_no, f"Your backlog for subject {backlog.subject.subject_name} has been cleared with score {cleared_marks}.")
        
        db.session.commit()
        flash('Backlog successfully cleared.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing backlog: {str(e)}', 'error')
        
    return redirect(url_for('view_backlogs'))

# --- ADMIN ANALYTICS ---
def get_analytics_summary():
    all_marks = Marks.query.all()
    from collections import defaultdict
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
        summary.append({
            'course': course,
            'semester': semester,
            'avg_marks': round(avg_marks, 2),
            'pass_percentage': round(pass_pct, 2),
            'total_students': total_students
        })
    summary.sort(key=lambda x: (x['course'], x['semester']))
    return summary

@app.route('/admin/analytics')
@login_required('admin')
def admin_analytics():
    summary = get_analytics_summary()
    return render_template('admin_analytics.html', summary=summary)

@app.route('/admin/analytics/export')
@login_required('admin')
def export_analytics_csv():
    summary = get_analytics_summary()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Course', 'Semester', 'Total Students', 'Average Marks', 'Pass Percentage'])
    for s in summary:
        writer.writerow([s['course'], s['semester'], s['total_students'], s['avg_marks'], s['pass_percentage']])
        
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    
    return send_file(
        mem,
        as_attachment=True,
        download_name="academic_analytics.csv",
        mimetype="text/csv"
    )

# --- SCORECARD VERIFICATION ROUTE ---
@app.route('/verify/<token>')
def verify_scorecard(token):
    verification = Verification.query.filter_by(token=token).first_or_404()
    student = Student.query.get(verification.roll_no)
    student_marks = Marks.query.filter_by(roll_no=verification.roll_no, semester=verification.semester).all()
    marks_list = [{
        'subject_name': m.subject.subject_name if m.subject else 'Unknown',
        'marks': m.marks
    } for m in student_marks]
    
    return render_template(
        'verify_scorecard.html',
        verification=verification,
        student=student,
        marks_list=marks_list
    )

# --- SCORECARD PDF DOWNLOAD ---
@app.route('/student/result/pdf/<int:roll_no>')
@login_required(['admin', 'teacher', 'student'])
def download_result_pdf(roll_no):
    student = Student.query.get_or_404(roll_no)
    
    # Restrict students to only download their own scorecard
    if session.get('role') == 'student' and session.get('roll_no') != roll_no:
        flash('Unauthorized PDF access.', 'error')
        return redirect(url_for('home'))
        
    # Get semester from query parameters
    semester_arg = request.args.get('semester')
    semester = int(semester_arg) if semester_arg else None
    
    # Gather marks
    if semester:
        student_marks = Marks.query.filter_by(roll_no=roll_no, semester=semester).all()
    else:
        student_marks = Marks.query.filter_by(roll_no=roll_no).all()
        
    marks_list = []
    for sm in student_marks:
        marks_list.append({
            'subject_name': sm.subject.subject_name if sm.subject else 'Unknown',
            'marks': sm.marks
        })
        
    if not marks_list:
        flash('No marks recorded yet, cannot generate PDF scorecard.', 'error')
        if session.get('role') == 'student':
            return redirect(url_for('student_dashboard'))
        return redirect(url_for('marks_report', semester=student.semester))
        
    target_semester = semester if semester else student.semester
    
    # Compute SGPA and CGPA
    sgpa = compute_gpa(roll_no, target_semester)
    cgpa = compute_gpa(roll_no)
    
    student_info = {
        'roll_no': student.roll_no,
        'name': student.name,
        'course': student.course,
        'semester': target_semester,
        'sgpa': sgpa,
        'cgpa': cgpa
    }
    
    # Generate verification token & QR code
    secret = "srms_super_secret_verification_key_98765"
    marks_str = ",".join(f"{m.subject_id}:{m.marks}" for m in student_marks)
    raw_str = f"{roll_no}:{target_semester}:{marks_str}:{secret}"
    hash_val = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()
    
    verification = Verification.query.filter_by(roll_no=roll_no, semester=target_semester).first()
    if not verification or verification.hash_val != hash_val:
        if not verification:
            token = uuid.uuid4().hex
            verification = Verification(
                token=token,
                roll_no=roll_no,
                semester=target_semester,
                hash_val=hash_val
            )
            db.session.add(verification)
        else:
            verification.hash_val = hash_val
            token = verification.token
        db.session.commit()
    else:
        token = verification.token
        
    # Generate QR Code image
    qr_url = url_for('verify_scorecard', token=token, _external=True)
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    
    pdf_buffer = generate_pdf(student_info, marks_list, qr_image_buffer=qr_buffer)
    suffix = f"_Sem{target_semester}" if semester else ""
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"Result_{roll_no}{suffix}.pdf",
        mimetype="application/pdf"
    )


# --- DATABASE SEED UTILITY ---
def seed_database():
    with app.app_context():
        # Create all tables
        db.create_all()
        check_and_add_credits_column()
        
        # 1. Seed system settings
        if not SystemSetting.query.filter_by(key='at_risk_threshold').first():
            db.session.add(SystemSetting(key='at_risk_threshold', value='55.0'))
            
        # 2. Seed grading scheme
        if not GradingScheme.query.first():
            schemes = [
                GradingScheme(grade_letter='A', min_pct=75.0, max_pct=100.0, grade_point=10.0),
                GradingScheme(grade_letter='B', min_pct=60.0, max_pct=74.99, grade_point=8.0),
                GradingScheme(grade_letter='C', min_pct=50.0, max_pct=59.99, grade_point=6.0),
                GradingScheme(grade_letter='F', min_pct=0.0, max_pct=49.99, grade_point=0.0),
            ]
            db.session.add_all(schemes)
            db.session.commit()

        # Check if Admin table is empty
        if not Admin.query.first():
            print("Seeding database with mock records...")
            import random
            
            # Add admin
            admin = Admin(username='admin', password='admin123')
            db.session.add(admin)
            
            # Add teachers
            teachers = [
                Teacher(teacher_id='T101', name='Jane Smith', course='BCA', password='teacher123'),
                Teacher(teacher_id='T102', name='John Doe', course='B.Tech', password='teacher123'),
                Teacher(teacher_id='T103', name='Sarah Connor', course='BA', password='teacher123')
            ]
            db.session.add_all(teachers)
            
            # Add subjects
            subjects_data = {
                ('BCA', 1): ['C Programming', 'Principles of Management', 'Business Communication'],
                ('BCA', 2): ['Data Structures', 'Discrete Mathematics', 'Database Systems'],
                ('BCA', 3): ['Java Programming', 'Operating Systems', 'Computer Networks'],
                ('BCA', 4): ['Web Technologies', 'Software Engineering', 'Python Development'],
                ('BCA', 5): ['Linux Administration', 'PHP & MySQL', 'Cloud Computing'],
                ('BCA', 6): ['Artificial Intelligence', 'Cyber Security', 'Major Project'],
                
                ('B.Tech', 1): ['Engineering Mathematics I', 'Engineering Physics', 'Programming in C'],
                ('B.Tech', 2): ['Engineering Mathematics II', 'Engineering Chemistry', 'Data Structures'],
                ('B.Tech', 3): ['Object Oriented Programming', 'Digital Logic Design', 'Discrete Structures'],
                ('B.Tech', 4): ['Database Management Systems', 'Theory of Computation', 'Computer Architecture'],
                ('B.Tech', 5): ['Design and Analysis of Algorithms', 'Operating Systems', 'Software Engineering'],
                ('B.Tech', 6): ['Computer Networks', 'Compiler Design', 'Web Engineering'],
                ('B.Tech', 7): ['Cryptography & Network Security', 'Cloud Computing', 'Distributed Systems'],
                ('B.Tech', 8): ['Machine Learning', 'Major Project', 'Seminar'],
                
                ('BA', 1): ['Introduction to Sociology', 'Micro Economics', 'English Literature I'],
                ('BA', 2): ['Social Psychology', 'Macro Economics', 'English Literature II'],
                ('BA', 3): ['Political Science I', 'History of India I', 'Environmental Studies'],
                ('BA', 4): ['Political Science II', 'History of India II', 'Public Administration'],
                ('BA', 5): ['International Relations', 'Indian Economy', 'Human Rights'],
                ('BA', 6): ['Global Politics', 'Social Philosophy', 'Research Methodology']
            }
            
            added_subjects = []
            for (course, sem), sub_list in subjects_data.items():
                for name in sub_list:
                    credits_val = random.choice([3, 4])
                    sub = Subject(subject_name=name, course=course, semester=sem, credits=credits_val)
                    db.session.add(sub)
                    added_subjects.append(sub)
            
            db.session.flush() # Flush to populate auto-increment IDs
            
            # Add students
            student_names = [
                "Ethan Hunt", "Clara Oswald", "David Tennant", "Rose Tyler", "Martha Jones",
                "Donna Noble", "Peter Parker", "Bruce Wayne", "Clark Kent", "Diana Prince",
                "Barry Allen", "Hal Jordan", "Arthur Curry", "Victor Stone", "Wanda Maximoff",
                "Steve Rogers", "Tony Stark", "Bruce Banner", "Natasha Romanoff", "Clint Barton",
                "Thor Odinson", "Loki Laufeyson", "Stephen Strange", "Peter Quill", "Gamora Zen",
                "Groot", "Rocket Raccoon", "Drax Destroyer", "Mantis", "Nebula", "Wade Wilson",
                "Logan Howlett", "Charles Xavier", "Jean Grey", "Scott Summers", "Ororo Munroe",
                "Bobby Drake", "Hank McCoy", "Remy LeBeau", "Anna Marie", "Kurt Wagner"
            ]
            
            student_idx = 0
            roll_no_counter = 5001
            
            courses_sems = [
                ('BCA', 6),
                ('B.Tech', 8),
                ('BA', 6)
            ]
            
            for course, max_sem in courses_sems:
                for sem in range(1, max_sem + 1):
                    for s_num in range(1, 3):
                        name = student_names[student_idx % len(student_names)]
                        display_name = f"{name} ({course} S{sem})"
                        gender = 'Male' if student_idx % 2 == 0 else 'Female'
                        dob = datetime.strptime('2005-05-15', '%Y-%m-%d').date()
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
                            semester=sem
                        )
                        db.session.add(student)
                        
                        for prev_sem in range(1, sem + 1):
                            subjects_for_term = [sub for sub in added_subjects if sub.course == course and sub.semester == prev_sem]
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
                                    semester=prev_sem
                                )
                                db.session.add(marks_rec)
                                
                                # Log audit
                                log_audit('create', roll_no_counter, sub.id, None, marks_val)
                                
                                if marks_val < 50:
                                    backlog = Backlog(
                                        roll_no=roll_no_counter,
                                        subject_id=sub.id,
                                        semester=prev_sem,
                                        original_marks=marks_val,
                                        status='pending'
                                    )
                                    db.session.add(backlog)
                                    
                        # Seed a sample notification
                        notify_user('student', roll_no_counter, f"Welcome to the portal. Semester {sem} grades are published.")
                        
                        roll_no_counter += 1
                        student_idx += 1
                        
            db.session.commit()
            print("Database seeding completed.")


if __name__ == '__main__':
    seed_database()
    app.run(debug=True, host='0.0.0.0', port=5000)
