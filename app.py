from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from config import Config
from database import db
from models import Admin, Student, Teacher, Subject, Marks
from utils.pdf_generator import generate_pdf
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

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
            if not marks_record:
                marks_record = Marks(
                    roll_no=roll_no, subject_id=sub.id, marks=mark_val,
                    course=course, semester=semester
                )
                db.session.add(marks_record)
            else:
                marks_record.marks = mark_val
                
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
    
    if semester:
        # Get students matching the semester
        # If teacher is logged in, filter report to only show students matching teacher's assigned course
        if session.get('role') == 'teacher':
            students = Student.query.filter_by(semester=semester, course=session.get('course')).all()
        else:
            students = Student.query.filter_by(semester=semester).all()
            
        for s in students:
            # Fetch marks for student
            student_marks = Marks.query.filter_by(roll_no=s.roll_no, semester=semester).all()
            
            # Construct a map of subjects -> marks
            subjects_map = {}
            for sm in student_marks:
                if sm.subject:
                    subjects_map[sm.subject.subject_name] = sm.marks
                    
            if subjects_map: # Only include if they have marks recorded
                report.append({
                    'roll_no': s.roll_no,
                    'name': s.name,
                    'course': s.course,
                    'semester': s.semester,
                    'subjects': subjects_map
                })
                
        # Sort report by roll number
        report.sort(key=lambda x: x['roll_no'])
        
    return render_template('marks_report.html', report=report, semester=semester)

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
                mr.marks = int(new_mark)
                
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
        
        if percentage >= 75:
            grade = "A"
        elif percentage >= 60:
            grade = "B"
        elif percentage >= 50:
            grade = "C"
        else:
            grade = "F"
            
        status = "PASS" if percentage >= 50 else "FAIL"
        
        sem_stats[sem] = {
            'marks': marks,
            'total': total,
            'max_possible': max_possible,
            'percentage': round(percentage, 2),
            'grade': grade,
            'status': status
        }
        
    overall_percentage = (overall_total / overall_max * 100) if overall_max > 0 else 0
    if overall_max > 0:
        if overall_percentage >= 75:
            overall_grade = "A"
        elif overall_percentage >= 60:
            overall_grade = "B"
        elif overall_percentage >= 50:
            overall_grade = "C"
        else:
            overall_grade = "F"
        overall_status = "PASS" if overall_percentage >= 50 else "FAIL"
    else:
        overall_grade = "N/A"
        overall_status = "N/A"
        
    return render_template(
        'student_dashboard.html', 
        student=student, 
        sorted_sems=sorted_sems,
        sem_stats=sem_stats,
        overall_percentage=round(overall_percentage, 2),
        overall_grade=overall_grade,
        overall_status=overall_status
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
        
    student_info = {
        'roll_no': student.roll_no,
        'name': student.name,
        'course': student.course,
        'semester': semester if semester else student.semester
    }
    
    pdf_buffer = generate_pdf(student_info, marks_list)
    suffix = f"_Sem{semester}" if semester else ""
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
        
        # Check if Admin table is empty
        if not Admin.query.first():
            print("Seeding database with mock records...")
            import random
            
            # 1. Add admin
            admin = Admin(username='admin', password='admin123')
            db.session.add(admin)
            
            # 2. Add teachers
            teachers = [
                Teacher(teacher_id='T101', name='Jane Smith', course='BCA', password='teacher123'),
                Teacher(teacher_id='T102', name='John Doe', course='B.Tech', password='teacher123'),
                Teacher(teacher_id='T103', name='Sarah Connor', course='BA', password='teacher123')
            ]
            db.session.add_all(teachers)
            
            # 3. Add subjects
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
                    sub = Subject(subject_name=name, course=course, semester=sem)
                    db.session.add(sub)
                    added_subjects.append(sub)
            
            db.session.flush() # Flush to populate auto-increment IDs
            
            # 4. Add students
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
                                marks_val = random.randint(65, 98)
                                marks_rec = Marks(
                                    roll_no=roll_no_counter,
                                    subject_id=sub.id,
                                    marks=marks_val,
                                    course=course,
                                    semester=prev_sem
                                )
                                db.session.add(marks_rec)
                        
                        roll_no_counter += 1
                        student_idx += 1
                        
            db.session.commit()
            print("Database seeding completed.")


if __name__ == '__main__':
    seed_database()
    app.run(debug=True, host='0.0.0.0', port=5000)
