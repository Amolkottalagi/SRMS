from database import db
from datetime import datetime

class Admin(db.Model):
    __tablename__ = 'admin'
    username = db.Column(db.String(50), primary_key=True)
    password = db.Column(db.String(255), nullable=False)

    def to_dict(self):
        return {
            'username': self.username
        }

class Student(db.Model):
    __tablename__ = 'student'
    roll_no = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    email = db.Column(db.String(100), nullable=False)
    contact_no = db.Column(db.String(15), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    semester = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            'roll_no': self.roll_no,
            'name': self.name,
            'gender': self.gender,
            'dob': self.dob.strftime('%Y-%m-%d') if self.dob else '',
            'email': self.email,
            'contact_no': self.contact_no,
            'course': self.course,
            'semester': self.semester
        }

class Teacher(db.Model):
    __tablename__ = 'teacher'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    teacher_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(255), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'teacher_id': self.teacher_id,
            'name': self.name,
            'course': self.course
        }

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subject_name = db.Column(db.String(100), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    credits = db.Column(db.Integer, default=3, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'subject_name': self.subject_name,
            'course': self.course,
            'semester': self.semester,
            'credits': self.credits
        }

class Marks(db.Model):
    __tablename__ = 'marks'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    roll_no = db.Column(db.Integer, db.ForeignKey('student.roll_no', ondelete='CASCADE'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    marks = db.Column(db.Integer, nullable=False)
    course = db.Column(db.String(50), nullable=False)
    semester = db.Column(db.Integer, nullable=False)

    # Relationships
    student = db.relationship('Student', backref=db.backref('marks_list', cascade='all, delete-orphan'))
    subject = db.relationship('Subject', backref=db.backref('marks_list', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'roll_no': self.roll_no,
            'subject_id': self.subject_id,
            'marks': self.marks,
            'course': self.course,
            'semester': self.semester
        }

class GradingScheme(db.Model):
    __tablename__ = 'grading_schemes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    grade_letter = db.Column(db.String(5), nullable=False)
    min_pct = db.Column(db.Float, nullable=False)
    max_pct = db.Column(db.Float, nullable=False)
    grade_point = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'grade_letter': self.grade_letter,
            'min_pct': self.min_pct,
            'max_pct': self.max_pct,
            'grade_point': self.grade_point
        }

class Backlog(db.Model):
    __tablename__ = 'backlogs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    roll_no = db.Column(db.Integer, db.ForeignKey('student.roll_no', ondelete='CASCADE'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    original_marks = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'cleared'
    cleared_marks = db.Column(db.Integer, nullable=True)
    cleared_date = db.Column(db.DateTime, nullable=True)

    # Relationships
    student = db.relationship('Student', backref=db.backref('backlogs_list', cascade='all, delete-orphan'))
    subject = db.relationship('Subject', backref=db.backref('backlogs_list', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'roll_no': self.roll_no,
            'subject_id': self.subject_id,
            'semester': self.semester,
            'original_marks': self.original_marks,
            'status': self.status,
            'cleared_marks': self.cleared_marks,
            'cleared_date': self.cleared_date.strftime('%Y-%m-%d %H:%M:%S') if self.cleared_date else None
        }

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_role = db.Column(db.String(20), nullable=False)  # 'student', 'teacher', 'admin'
    user_id = db.Column(db.String(50), nullable=False)    # roll_no, teacher_id, or username
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_role': self.user_role,
            'user_id': self.user_id,
            'message': self.message,
            'is_read': self.is_read,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    actor_role = db.Column(db.String(20), nullable=False)  # 'admin', 'teacher'
    actor_id = db.Column(db.String(50), nullable=False)    # username, teacher_id
    action = db.Column(db.String(50), nullable=False)      # 'create', 'edit'
    target_roll_no = db.Column(db.Integer, nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    old_value = db.Column(db.Integer, nullable=True)
    new_value = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    subject = db.relationship('Subject')

    def to_dict(self):
        return {
            'id': self.id,
            'actor_role': self.actor_role,
            'actor_id': self.actor_id,
            'action': self.action,
            'target_roll_no': self.target_roll_no,
            'subject_id': self.subject_id,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

class Verification(db.Model):
    __tablename__ = 'verifications'
    token = db.Column(db.String(64), primary_key=True)
    roll_no = db.Column(db.Integer, db.ForeignKey('student.roll_no', ondelete='CASCADE'), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    hash_val = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    student = db.relationship('Student')

    def to_dict(self):
        return {
            'token': self.token,
            'roll_no': self.roll_no,
            'semester': self.semester,
            'hash_val': self.hash_val,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(50), nullable=False)

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value
        }
