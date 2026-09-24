from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class Admin(Base):
    __tablename__ = 'admin'
    username = Column(String(50), primary_key=True)
    password = Column(String(255), nullable=False)

    def to_dict(self):
        return {
            'username': self.username
        }


class Student(Base):
    __tablename__ = 'student'
    roll_no = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    gender = Column(String(10), nullable=False)
    dob = Column(Date, nullable=False)
    email = Column(String(100), nullable=False)
    contact_no = Column(String(15), nullable=False)
    course = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)

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


class Teacher(Base):
    __tablename__ = 'teacher'
    id = Column(Integer, primary_key=True, autoincrement=True)
    teacher_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    course = Column(String(50), nullable=False)
    password = Column(String(255), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'teacher_id': self.teacher_id,
            'name': self.name,
            'course': self.course
        }


class Subject(Base):
    __tablename__ = 'subjects'
    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_name = Column(String(100), nullable=False)
    course = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)
    credits = Column(Integer, default=3, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'subject_name': self.subject_name,
            'course': self.course,
            'semester': self.semester,
            'credits': self.credits
        }


class Marks(Base):
    __tablename__ = 'marks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    roll_no = Column(Integer, ForeignKey('student.roll_no', ondelete='CASCADE'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    marks = Column(Integer, nullable=False)
    course = Column(String(50), nullable=False)
    semester = Column(Integer, nullable=False)

    # Relationships
    student = relationship('Student', backref='marks_list')
    subject = relationship('Subject', backref='marks_list')

    def to_dict(self):
        return {
            'id': self.id,
            'roll_no': self.roll_no,
            'subject_id': self.subject_id,
            'marks': self.marks,
            'course': self.course,
            'semester': self.semester
        }


class GradingScheme(Base):
    __tablename__ = 'grading_schemes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    grade_letter = Column(String(5), nullable=False)
    min_pct = Column(Float, nullable=False)
    max_pct = Column(Float, nullable=False)
    grade_point = Column(Float, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'grade_letter': self.grade_letter,
            'min_pct': self.min_pct,
            'max_pct': self.max_pct,
            'grade_point': self.grade_point
        }


class Backlog(Base):
    __tablename__ = 'backlogs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    roll_no = Column(Integer, ForeignKey('student.roll_no', ondelete='CASCADE'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    semester = Column(Integer, nullable=False)
    original_marks = Column(Integer, nullable=False)
    status = Column(String(20), default='pending', nullable=False)  # 'pending', 'cleared'
    cleared_marks = Column(Integer, nullable=True)
    cleared_date = Column(DateTime, nullable=True)

    # Relationships
    student = relationship('Student', backref='backlogs_list')
    subject = relationship('Subject', backref='backlogs_list')

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


class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_role = Column(String(20), nullable=False)  # 'student', 'teacher', 'admin'
    user_id = Column(String(50), nullable=False)    # roll_no, teacher_id, or username
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_role': self.user_role,
            'user_id': self.user_id,
            'message': self.message,
            'is_read': self.is_read,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_role = Column(String(20), nullable=False)  # 'admin', 'teacher'
    actor_id = Column(String(50), nullable=False)    # username, teacher_id
    action = Column(String(50), nullable=False)      # 'create', 'edit'
    target_roll_no = Column(Integer, nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    old_value = Column(Integer, nullable=True)
    new_value = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    subject = relationship('Subject')

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


class Verification(Base):
    __tablename__ = 'verifications'
    token = Column(String(64), primary_key=True)
    roll_no = Column(Integer, ForeignKey('student.roll_no', ondelete='CASCADE'), nullable=False)
    semester = Column(Integer, nullable=False)
    hash_val = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    student = relationship('Student')

    def to_dict(self):
        return {
            'token': self.token,
            'roll_no': self.roll_no,
            'semester': self.semester,
            'hash_val': self.hash_val,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key = Column(String(50), primary_key=True)
    value = Column(String(50), nullable=False)

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value
        }
