import unittest
from datetime import datetime
from app import app, db
from models import Admin, Student, Teacher, Subject, Marks

class SRMSIntegrationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Configure and initialize database once for all tests."""
        # Clean up database registration to allow re-initialization with memory DB
        app.extensions.pop('sqlalchemy', None)
        db._app_engines.pop(app, None)
        
        app.config['TESTING'] = True
        # Use an in-memory SQLite database for fast, isolated integration tests
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['SECRET_KEY'] = 'test_secret_key'
        
        db.init_app(app)

    def setUp(self):
        """Set up test app instance and in-memory database per test."""
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        # Create all database tables
        db.create_all()
        
        # Seed test admin
        self.test_admin = Admin(username='admin', password='admin123')
        db.session.add(self.test_admin)
        db.session.commit()

    def tearDown(self):
        """Clean up database session and tables after test."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_home_page_loads(self):
        """Test that the homepage renders correctly with the expected title/text."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Student Result Management', response.data)

    def test_unauthorized_access_redirects(self):
        """Test that protected pages redirect unauthorized users."""
        response = self.client.get('/admin/dashboard', follow_redirects=True)
        # Should redirect to home page with warning
        self.assertIn(b'Please sign in to access this page.', response.data)

    def test_admin_login_success(self):
        """Test that logging in with valid admin credentials succeeds."""
        # Post to login with correct credentials
        response = self.client.post('/login/admin', data={
            'username': 'admin',
            'password': 'admin123'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin successfully logged in.', response.data)
        self.assertIn(b'Admin Dashboard', response.data)

    def test_admin_login_failure(self):
        """Test that logging in with invalid admin credentials fails."""
        response = self.client.post('/login/admin', data={
            'username': 'admin',
            'password': 'wrongpassword'
        }, follow_redirects=True)
        
        self.assertIn(b'Invalid Admin Credentials.', response.data)

    def test_admin_crud_student(self):
        """Test admin logging in, creating, editing, and listing a student."""
        # Log in first
        with self.client:
            self.client.post('/login/admin', data={
                'username': 'admin',
                'password': 'admin123'
            })
            
            # Create a student
            response = self.client.post('/admin/students/new', data={
                'roll_no': '6001',
                'name': 'Test Student',
                'gender': 'Male',
                'dob': '2005-08-15',
                'email': 'teststudent@example.com',
                'contact_no': '9876543210',
                'course': 'BCA',
                'semester': '1'
            }, follow_redirects=True)
            
            self.assertIn(b'Student registered successfully.', response.data)
            
            # Verify student exists in db
            student = Student.query.get(6001)
            self.assertIsNotNone(student)
            self.assertEqual(student.name, 'Test Student')
            
            # Edit the student
            response = self.client.post('/admin/students/edit/6001', data={
                'name': 'Test Student Updated',
                'gender': 'Male',
                'dob': '2005-08-15',
                'email': 'updated@example.com',
                'contact_no': '9876543210',
                'course': 'BCA',
                'semester': '2'
            }, follow_redirects=True)
            
            self.assertIn(b'Student profile updated.', response.data)
            
            # Verify changes in db
            db.session.refresh(student)
            self.assertEqual(student.name, 'Test Student Updated')
            self.assertEqual(student.semester, 2)

    def test_student_login(self):
        """Test student login using their Date of Birth in DDMMYYYY format."""
        # 1. Create a student record first
        dob = datetime.strptime('2004-12-25', '%Y-%m-%d').date()
        student = Student(
            roll_no=7001,
            name='Jane Doe',
            gender='Female',
            dob=dob,
            email='jane@example.com',
            contact_no='9999988888',
            course='B.Tech',
            semester=1
        )
        db.session.add(student)
        db.session.commit()
        
        # 2. Login with correct DOB formatted as DDMMYYYY -> '25122004'
        response = self.client.post('/login/student', data={
            'roll_no': '7001',
            'password': '25122004'
        }, follow_redirects=True)
        
        self.assertIn(b'Welcome, Jane Doe', response.data)

    def test_logout(self):
        """Test session logout."""
        # Log in first
        self.client.post('/login/admin', data={
            'username': 'admin',
            'password': 'admin123'
        })
        
        # Logout
        response = self.client.get('/logout', follow_redirects=True)
        self.assertIn(b'Logged out successfully.', response.data)
        
        # Verify dashboard is no longer accessible
        response_dash = self.client.get('/admin/dashboard', follow_redirects=True)
        self.assertIn(b'Please sign in to access this page.', response_dash.data)

if __name__ == '__main__':
    unittest.main()
