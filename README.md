# 🎓 SRMS — Student Result Management System

A full-stack web application for managing student academic records, built with a modern, production-style Python backend. SRMS provides role-based portals for administrators, teachers, and students to manage results, track academic performance, and issue tamper-verifiable digital scorecards.


---

## 📌 Overview

SRMS digitizes the end-to-end academic result workflow for an educational institution — from marks entry and grade computation to result publication and public verification. It replaces manual, spreadsheet-driven result processing with a secure, auditable, role-based system.

The project was built to demonstrate practical backend engineering skills: RESTful API design, relational data modeling, authentication and authorization, business-logic implementation (GPA/rank/at-risk analytics), and document generation with cryptographic verification.

---

## ✨ Key Features

### 🔐 Role-Based Access Control
- Three distinct portals — **Admin**, **Teacher**, and **Student** — each with scoped permissions
- Session-based authentication with hashed credentials (bcrypt)

### 🧑‍🎓 Academic Records Management
- Full CRUD for students, teachers, and subjects
- Semester-wise marks entry and editing, with per-teacher course restrictions
- Automatic backlog tracking and clearance workflow

### 📊 Analytics & Insights
- Automated **SGPA / CGPA** computation using a configurable, credit-weighted grading scheme
- **Class rank and percentile** calculation per course and semester
- **At-risk student detection** — flags students below a configurable threshold or on a declining 3-semester trend
- CSV export of institution-wide analytics

### 📄 Verifiable Digital Scorecards
- On-demand PDF result generation (ReportLab)
- Each scorecard embeds a **QR code** linking to a public, login-free verification page — enabling third parties (employers, other institutions) to confirm authenticity without system access

### 🔔 Notifications & Audit Trail
- In-app notification system for grade updates and backlog clearance
- Full audit log capturing every marks change, by actor, with before/after values

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend Framework** | FastAPI (ASGI) |
| **ORM / Database** | SQLAlchemy · SQLite (dev) / MySQL (production-ready) |
| **Templating** | Jinja2 |
| **Auth & Security** | Session-based auth · bcrypt password hashing |
| **PDF Generation** | ReportLab |
| **QR Code Generation** | qrcode + Pillow |
| **Server** | Uvicorn (ASGI) |

---

## 🏗️ Architecture

The application follows a layered, router-based architecture rather than a single monolithic file — mirroring how production FastAPI services are structured:
Request → Router (auth / admin / marks / teacher / student / api)
↓
Dependency Injection (DB session via get_db)
↓
Business Logic Layer (utils.py — GPA, rank, at-risk detection)
↓
ORM Models (SQLAlchemy) → Database
↓
Jinja2 Templates → Rendered HTML Response


**Design decisions:**
- **Separation of concerns** — business logic (`utils.py`) is fully decoupled from route handlers, making it independently unit-testable.
- **Dependency-injected DB sessions** — each request gets a scoped session that's guaranteed to close, avoiding connection leaks.
- **Environment-driven configuration** — the same codebase runs on SQLite locally and MySQL in production via a single `DATABASE_URL` variable.

---

## 📂 Project Structure

srms_fastapi/ <br>
├── app/<br>
│ ├── main.py # App entrypoint, middleware, router registration<br>
│ ├── config.py # Environment-based configuration<br>
│ ├── database.py # Engine, session factory, DB dependency<br>
│ ├── models.py # SQLAlchemy ORM models<br>
│ ├── security.py # Password hashing, session auth, flash messaging<br>
│ ├── utils.py # GPA/rank/at-risk business logic<br>
│ ├── pdf_generator.py # PDF + QR scorecard generation<br>
│ ├── seed.py # Demo data seeding<br>
│ └── routers/ # Feature-scoped route modules<br>
├── templates/ # Jinja2 views<br>
├── static/ # CSS assets<br>
└── requirements.txt<br>


---

## 🚀 Getting Started

```bash
git clone <your-repo-url>
cd srms_fastapi
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

The app will be available at **http://127.0.0.1:8000**, with demo data seeded automatically.

### Demo Credentials
| Role | Login | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| Teacher | `T101` | `teacher123` |
| Student | `5001` | `15052005` (DOB) |

### Using MySQL
```bash
export DATABASE_URL="mysql+pymysql://user:password@localhost:3306/srms"
python run.py
```

---

## 🔒 Security Notes

- Passwords are hashed with **bcrypt** before storage — never stored or compared in plaintext.
- Scorecard verification uses a hashed token, so a printed result's authenticity can be confirmed without exposing student data through guessable URLs.
- Role checks are enforced at the route level for every protected endpoint.

---

## 🗺️ Roadmap

- [ ] JWT-based API authentication for a decoupled frontend/mobile client
- [ ] Alembic-managed database migrations
- [ ] Automated test suite (pytest)
- [ ] Pagination for large student/marks datasets
- [ ] Dockerized deployment


---

## 👤 Author

Amol Kottalagi <br>
kottalagiamol05@gmail.com
