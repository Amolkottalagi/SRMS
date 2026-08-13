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

    def to_dict(self):
        return {
            'id': self.id,
            'subject_name': self.subject_name,
            'course': self.course,
            'semester': self.semester
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
