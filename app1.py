from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message
import google.generativeai as genai
import os
from PyPDF2 import PdfReader
import io
from dotenv import load_dotenv
import re
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey123456")
s = URLSafeTimedSerializer(app.secret_key)

# ----------------------
# Database connection
# ----------------------
def get_db_connection():
    try:
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            database=os.getenv("DB_NAME"),
            autocommit=True
        )
        return db
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

# ----------------------
# Database initialization
# ----------------------
def initialize_database():
    db = get_db_connection()
    if not db:
        print("Database connection failed!")
        return
    cursor = db.cursor()

    tables = [
        """CREATE TABLE IF NOT EXISTS users (
            id INT PRIMARY KEY AUTO_INCREMENT,
            email VARCHAR(255) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS resumes (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            filename VARCHAR(255),
            filedata LONGBLOB,
            resumetext LONGTEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS companies (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            requirements TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS topics (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS questions (
            id INT PRIMARY KEY AUTO_INCREMENT,
            title VARCHAR(500) NOT NULL,
            description TEXT,
            type ENUM('system_design', 'behavioral', 'data_structures', 'algorithms', 'other') NOT NULL,
            company_id INT,
            topic_id INT,
            views INT DEFAULT 0,
            likes INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
            FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL
        )""",
        """CREATE TABLE IF NOT EXISTS interview_answers (
           id INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
           question TEXT,
           answer TEXT,
           feedback TEXT
        )"""
    ]

    for sql in tables:
        cursor.execute(sql)

    cursor.close()
    db.close()
    print("✅ Database initialization complete!")

# ----------------------
# Flask-Mail config
# ----------------------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USER")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASS")
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

mail = Mail(app)

# ----------------------
# Gemini API key
# ----------------------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ----------------------
# Login required decorator
# ----------------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login first.", "error")
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

# ----------------------
# Basic routes
# ----------------------
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        confirm = request.form['confirm-password']

        if password != confirm:
            flash("Passwords do not match!", "error")
            return redirect(url_for('signup'))

        db = get_db_connection()
        if not db:
            flash("Database error", "error")
            return redirect(url_for('signup'))

        cursor = db.cursor(dictionary=True)
        try:
            hashed = generate_password_hash(password)
            cursor.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed))
            db.commit()
            flash("Account created successfully! Please login.", "success")
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            flash("Email already exists!", "error")
        finally:
            cursor.close()
            db.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        db = get_db_connection()
        if not db:
            flash("Database error", "error")
            return redirect(url_for('login'))

        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password!", "error")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for('login'))

# ----------------------
# Dashboard and static pages
# ----------------------
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route("/pyqs")
@login_required
def pyqs():
    return render_template("pyqs.html")

@app.route("/history")
@login_required
def history():
    return render_template("history.html")

@app.route("/pricing")
@login_required
def pricing():
    return render_template("pricing.html")

@app.route("/contact")
@login_required
def contact():
    return render_template("contact.html")

@app.route("/about")
@login_required
def about():
    return render_template("about.html")

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")

# ----------------------
# Resume upload
# ----------------------
@app.route("/upload", methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash("No file uploaded!", "error")
            return redirect(url_for('upload'))

        file = request.files['resume']
        if file.filename == '':
            flash("No file selected!", "error")
            return redirect(url_for('upload'))

        try:
            file_data = file.read()
            filename = file.filename
            resume_text = ""

            if filename.lower().endswith(".pdf"):
                pdf = PdfReader(io.BytesIO(file_data))
                resume_text = " ".join([page.extract_text() or "" for page in pdf.pages])
            elif filename.lower().endswith((".txt", ".docx")):
                resume_text = file_data.decode('utf-8', errors='ignore')

            db = get_db_connection()
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO resumes (user_id, filename, filedata, resumetext) VALUES (%s, %s, %s, %s)",
                (session['user_id'], filename, file_data, resume_text)
            )
            db.commit()
            cursor.close()
            db.close()

            flash("Resume uploaded successfully!", "success")
            return redirect(url_for('screen'))

        except Exception as e:
            flash(f"Error uploading file: {e}", "error")
            return redirect(url_for('upload'))

    return render_template('upload.html')

# ----------------------
# Screen page: show current question
# ----------------------
@app.route("/screen")
def screen():
    # Get current state from session
    current_index = session.get("current_index", 0)
    total_questions = session.get("total_questions", 5)
    current_question = session.get("current_question")

    # Initialize first question if not set
    if not current_question:
        current_question = "Tell me about yourself."
        session["current_question"] = current_question
        session["current_index"] = 0

    # Get last AI feedback if available
    feedback = session.get("last_feedback", "")

    return render_template(
        "screen.html",
        current_question=current_question,
        question_index=current_index,
        total_questions=total_questions,
        feedback=feedback
    )

# ----------------------
# Ask endpoint: submit answer and generate next question
# ----------------------
@app.route("/ask", methods=["POST"])
def ask():
    user_answer = request.form.get("answer", "").strip()
    question = request.form.get("question", "").strip()

    if not user_answer or not question:
        return redirect(url_for("screen"))

    # Save answer in DB
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS interview_answers (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT, feedback TEXT)"
    )
    cursor.execute(
        "INSERT INTO interview_answers (question, answer) VALUES (?, ?)",
        (question, user_answer)
    )
    db.commit()
    answer_id = cursor.lastrowid
    cursor.close()
    db.close()

    # Get AI feedback
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"Evaluate the answer and give feedback.\nQuestion: {question}\nAnswer: {user_answer}"
        response = model.generate_content(prompt)
        ai_feedback = response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        ai_feedback = "AI feedback not available."

    # Save feedback in session
    session["last_feedback"] = ai_feedback

    # Update session index
    session["current_index"] = session.get("current_index", 0) + 1

    # Generate next question if not last
    if session["current_index"] < session.get("total_questions", 5):
        try:
            prompt_new = "You are a mock interviewer. Generate a new interview question."
            response_new = model.generate_content(prompt_new)
            next_question = response_new.text.strip() or "Tell me about a challenge you faced."
        except:
            next_question = "Tell me about a challenge you faced."
        session["current_question"] = next_question
    else:
        # Last question reached
        session["current_question"] = None
        return redirect(url_for("result"))

    return redirect(url_for("screen"))

# ----------------------
# Result page
# ----------------------
@app.route("/result")
def result():
    # Fetch all answers from DB (replace with your DB)
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT question, answer, feedback FROM interview_answers")
    all_answers = cursor.fetchall()
    cursor.close()
    db.close()

    # Clear session
    session.pop("current_question", None)
    session.pop("current_index", None)
    session.pop("last_feedback", None)

    return render_template("result.html", answers=all_answers)

@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email")
        # Here you can add logic to send a password reset email
        flash("If this email is registered, a password reset link has been sent.", "success")
        return redirect(url_for("login"))
    return render_template("forgot.html")

# ----------------------
# Run app
# ----------------------
if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)
