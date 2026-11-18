from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message
from groq import Groq
import os
from PyPDF2 import PdfReader
import io
from dotenv import load_dotenv
import json
import re
from functools import wraps
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from flask import send_file, make_response
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey123456")

s = URLSafeTimedSerializer(app.secret_key)

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
    
def initialize_database():
    db = get_db_connection()
    if not db:
        print("Database connection failed!")
        return
    cursor = db.cursor()

    # ----------------------
    # Create tables
    # ----------------------
    tables = [
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
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS ai_feedback (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            suggestions LONGTEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    ]

    for sql in tables:
        cursor.execute(sql)

    # ----------------------
    # Insert sample companies and topics
    # ----------------------
    cursor.execute("SELECT COUNT(*) FROM companies")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO companies (name, requirements) VALUES (%s, %s)",
            ("Google", "Strong CS fundamentals, Proficiency in C++ or Java, Problem-solving skills")
        )
        cursor.execute(
            "INSERT INTO companies (name, requirements) VALUES (%s, %s)",
            ("Meta", "System design, Algorithms, Behavioral skills")
        )
        cursor.execute(
            "INSERT INTO companies (name, requirements) VALUES (%s, %s)",
            ("Amazon", "Leadership principles, Data structures, System design")
        )

        topics = ["System Design", "Behavioral", "Data Structures", "Algorithms", "Database", "Networking"]
        for t in topics:
            cursor.execute("INSERT INTO topics (name) VALUES (%s)", (t,))

        db.commit()
        print("✅ Sample companies and topics inserted!")

    # ----------------------
    # Insert sample questions
    # ----------------------
    cursor.execute("SELECT COUNT(*) FROM questions")
    if cursor.fetchone()[0] == 0:
        # Get company IDs
        cursor.execute("SELECT id FROM companies WHERE name='Google'")
        google_id = cursor.fetchone()[0]

        cursor.execute("SELECT id FROM companies WHERE name='Meta'")
        meta_id = cursor.fetchone()[0]

        cursor.execute("SELECT id FROM companies WHERE name='Amazon'")
        amazon_id = cursor.fetchone()[0]

        # Get topic IDs
        cursor.execute("SELECT id FROM topics WHERE name='System Design'")
        system_design_id = cursor.fetchone()[0]

        cursor.execute("SELECT id FROM topics WHERE name='Behavioral'")
        behavioral_id = cursor.fetchone()[0]

        cursor.execute("SELECT id FROM topics WHERE name='Data Structures'")
        data_structures_id = cursor.fetchone()[0]

        # Insert questions
        sample_questions = [
            ("Design a URL shortening service like TinyURL",
             "Discuss the requirements, API design, data model, and how to handle hash collisions and generate unique short URLs. Consider scalability and performance.",
             "system_design", google_id, system_design_id, 12500, 3100),

            ("Tell me about a time you had a conflict with a coworker",
             "Describe the situation, the actions you took, and the outcome. Focus on your communication and problem-solving skills.",
             "behavioral", meta_id, behavioral_id, 8200, 1800),

            ("Find the median of two sorted arrays",
             "Given two sorted arrays, find the median of the two arrays efficiently.",
             "data_structures", amazon_id, data_structures_id, 6500, 1200)
        ]

        for q in sample_questions:
            cursor.execute(
                "INSERT INTO questions (title, description, type, company_id, topic_id, views, likes) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                q
            )

        db.commit()
        print("✅ Sample questions inserted!")

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
# Groq API client
# ----------------------
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ----------------------
# Helper: login required decorator
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
# Routes
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
            flash("Database connection error. Please try again.", "error")
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
        except Exception as e:
            flash(f"Database error: {str(e)}", "error")
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
            flash("Database connection error. Please try again.", "error")
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

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        email = request.form['email']

        db = get_db_connection()
        if not db:
            flash("Database connection error. Please try again.", "error")
            return redirect(url_for('forgot'))

        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user:
            try:
                token = s.dumps(email, salt='password-reset-salt')
                link = url_for('reset', token=token, _external=True)
                msg = Message('Password Reset Request', sender=app.config['MAIL_USERNAME'], recipients=[email])
                msg.body = f"Click this link to reset your password (valid for 1 hour): {link}"
                mail.send(msg)
            except Exception as e:
                print(f"Email sending error: {e}")

        flash("If this email exists, reset instructions were sent.", "info")
        return redirect(url_for('login'))

    return render_template('forgot.html')

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except:
        flash("The reset link is invalid or has expired.", "error")
        return redirect(url_for('forgot'))

    if request.method == 'POST':
        new_password = request.form['password']
        confirm = request.form['confirm']

        if new_password != confirm:
            flash("Passwords do not match!", "error")
            return redirect(request.url)

        db = get_db_connection()
        if not db:
            flash("Database connection error. Please try again.", "error")
            return redirect(url_for('forgot'))

        hashed = generate_password_hash(new_password)
        cursor = db.cursor()
        cursor.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
        db.commit()
        cursor.close()
        db.close()

        flash("Your password has been updated. Please login.", "success")
        return redirect(url_for('login'))

    return render_template('reset.html')

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
# Resume upload route
# ----------------------
@app.route("/upload", methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash("No file part!", "error")
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
                # Handle text files or add docx support if needed
                resume_text = file_data.decode('utf-8', errors='ignore')

            db = get_db_connection()
            if not db:
                flash("Database connection error. Please try again.", "error")
                return redirect(url_for('upload'))

            cursor = db.cursor()
            query = "INSERT INTO resumes (user_id, filename, filedata, resumetext) VALUES (%s, %s, %s, %s)"
            cursor.execute(query, (session['user_id'], filename, file_data, resume_text))
            db.commit()
            cursor.close()
            db.close()

            flash("Resume uploaded successfully!", "success")
            return redirect(url_for('screen'))

        except Exception as e:
            flash(f"Error uploading file: {str(e)}", "error")
            return redirect(url_for('upload'))

    return render_template('upload.html')

# ----------------------
# Mock interview screen - CORRECTED VERSION
# ----------------------
@app.route("/screen")
@login_required
def screen():
    # Clear any existing interview session
    session.pop("questions", None)
    session.pop("current_question_index", None)
    session.pop("answers", None)
    session.pop("current_question", None)
    
    # Initialize session variables
    session["answers"] = []
    session["current_question_index"] = 0
    session["total_questions"] = 5
    
    questions = []
    resume_text = ""

    try:
        # Get resume text from the latest upload
        db = get_db_connection()
        if db:
            cursor = db.cursor(dictionary=True)
            cursor.execute(
                "SELECT resumetext FROM resumes WHERE user_id=%s ORDER BY id DESC LIMIT 1", 
                (session['user_id'],)
            )
            resume_data = cursor.fetchone()
            cursor.close()
            db.close()
            
            if resume_data and resume_data['resumetext']:
                resume_text = resume_data['resumetext']
        
        # Generate questions based on resume or use default
        if resume_text and len(resume_text.strip()) > 50:
            prompt = f"""Generate exactly 5 professional interview questions based on this resume content. 
            Make the questions relevant to the candidate's background and skills.
            
            Resume Content:
            {resume_text[:3000]}
            
            Return ONLY the questions, one per line, numbered 1-5:"""
        else:
            prompt = """Generate exactly 5 professional interview questions for a general candidate.
            Return ONLY the questions, one per line, numbered 1-5:"""

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.7
        )

        raw_text = response.choices[0].message.content.strip()
        print("AI Generated Questions:", raw_text)

        # Extract questions more reliably
        questions = []
        lines = raw_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Remove numbering and clean up
            clean_line = re.sub(r'^\d+[\.\)]\s*', '', line)
            clean_line = re.sub(r'^[•\-*]\s*', '', clean_line)
            clean_line = re.sub(r'^(Question\s*\d*:?\s*)', '', clean_line, flags=re.IGNORECASE)
            
            if clean_line and len(clean_line) > 15:
                questions.append(clean_line)

    except Exception as e:
        print(f"Error generating questions: {e}")
        questions = []

    # Fallback questions if AI generation fails
    if len(questions) < 3:
        questions = [
            "Tell me about yourself and your professional background.",
            "What are your key strengths and how do they relate to this role?",
            "Describe a challenging project you worked on and how you handled it.",
            "How do you approach problem-solving when faced with technical difficulties?",
            "Where do you see your career heading in the next few years?"
        ]

    # Store only the first 5 questions
    questions = questions[:5]
    session["questions"] = questions
    session["total_questions"] = len(questions)
    session["current_question"] = questions[0] if questions else "Tell me about yourself."

    print(f"Final questions for interview: {questions}")

    return render_template("screen.html", 
                         current_question=session["current_question"],
                         question_index=session["current_question_index"],
                         total_questions=session["total_questions"])

# ----------------------
# Ask endpoint - CORRECTED VERSION
# ----------------------
@app.route('/ask', methods=['POST'])
@login_required
def ask():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        question = data.get("question")
        answer = data.get("answer")

        if not question or not answer:
            return jsonify({"error": "Question and answer are required"}), 400

        # Store answer in database
        db = get_db_connection()
        if db:
            cursor = db.cursor()
            try:
                cursor.execute(
                    "INSERT INTO interview_answers (user_id, question, answer) VALUES (%s, %s, %s)",
                    (session["user_id"], question, answer)
                )
                db.commit()
            except Exception as e:
                print(f"Database error: {e}")
            finally:
                cursor.close()
                db.close()

        # Add to session answers
        if "answers" not in session:
            session["answers"] = []
        session["answers"].append({"question": question, "answer": answer})

        # Get next question from session
        questions = session.get("questions", [])
        current_index = session.get("current_question_index", 0)
        
        # Move to next question
        next_index = current_index + 1
        session["current_question_index"] = next_index
        
        # Determine if this is the last question
        if next_index >= len(questions):
            is_last_question = True
            next_question = "Thank you for completing the interview!"
        else:
            is_last_question = False
            next_question = questions[next_index]
            session["current_question"] = next_question

        # Generate AI feedback
        try:
            feedback_prompt = f"""Provide brief, constructive feedback (2-3 sentences) for this interview answer:

            Question: "{question}"
            Answer: "{answer}"
            
            Focus on:
            - What was good about the response
            - One specific area for improvement
            
            Keep it professional and encouraging."""

            feedback_response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": feedback_prompt}],
                max_tokens=200,
                temperature=0.5
            )
            feedback = feedback_response.choices[0].message.content.strip()
        except Exception as e:
            print(f"AI feedback error: {e}")
            feedback = "Thank you for your thoughtful answer. Let's continue with the next question."

        return jsonify({
            "feedback": feedback, 
            "next_question": next_question,
            "is_last_question": is_last_question,
            "current_index": next_index,
            "total_questions": len(questions)
        })

    except Exception as e:
        print(f"Error in /ask endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500

# ----------------------
# Result page - ENHANCED VERSION
# ----------------------
@app.route("/result")
@login_required
def result():
    # Get recent answers from database
    answers = []
    db = get_db_connection()
    if db:
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT question, answer, created_at FROM interview_answers WHERE user_id=%s ORDER BY created_at ASC", 
                (session["user_id"],)
            )
            answers = cursor.fetchall()
        except Exception as e:
            print(f"Database error: {e}")
        finally:
            cursor.close()
            db.close()

    # Calculate performance metrics
    total_questions = len(answers)

    if total_questions > 0:
        answer_lengths = [len(answer['answer']) for answer in answers]
        avg_length = sum(answer_lengths) / len(answer_lengths)

        base_score = min(100, 60 + (total_questions * 6))
        if avg_length > 150:
            base_score += 10
        elif avg_length < 50:
            base_score -= 10

        confidence = max(0, min(100, base_score + 5))
        grammar = max(0, min(100, base_score + 10))
        clarity = max(0, min(100, base_score + 5))
        # Heuristic placeholders for tone and eye contact derived from clarity/confidence
        tone = max(0, min(100, int((grammar + clarity) / 2)))
        eye_contact = max(0, min(100, int((confidence + clarity) / 2)))
    else:
        base_score = confidence = grammar = clarity = tone = eye_contact = 0

    score = max(0, min(100, int(base_score)))

    # Generate breakdown and skills assessment
    breakdown = [clarity, confidence, score, grammar, min(100, score + 10)]
    tech_skills = [
        min(100, score - 5),
        min(100, score + 5),
        min(100, score - 10),
        min(100, score),
        min(100, score + 15)
    ]

    # Build score trend over time
    score_trend = []
    if total_questions > 0:
        incremental = max(1, int(score / max(1, total_questions)))
        current = max(40, score - incremental * (total_questions - 1))
        for _ in range(total_questions):
            score_trend.append(max(0, min(100, current)))
            current = min(100, current + incremental)

    # Ensure results directory exists
    static_results_dir = os.path.join(app.root_path, 'static', 'results')
    try:
        os.makedirs(static_results_dir, exist_ok=True)
    except Exception as e:
        print(f"Static results dir error: {e}")

    # Generate and save Matplotlib charts
    bar_chart_filename = f"bar_user_{session['user_id']}.png"
    line_chart_filename = f"line_user_{session['user_id']}.png"
    bar_chart_path = os.path.join(static_results_dir, bar_chart_filename)
    line_chart_path = os.path.join(static_results_dir, line_chart_filename)

    try:
        # Bar Chart: Confidence, Tone, Eye Contact
        plt.figure(figsize=(6, 4))
        categories = ['Confidence', 'Tone', 'Eye Contact']
        values = [confidence, tone, eye_contact]
        bars = plt.bar(categories, values, color=['#4913ec', '#8a2be2', '#6a5acd'])
        plt.ylim(0, 100)
        plt.title('Performance Attributes')
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width() / 2, height + 1, f"{int(height)}%", ha='center', va='bottom', fontsize=9)
        plt.tight_layout()
        plt.savefig(bar_chart_path, dpi=150)
        plt.close()

        # Line Chart: Interview Progress (score trend over time)
        plt.figure(figsize=(6, 4))
        if score_trend:
            plt.plot(range(1, len(score_trend) + 1), score_trend, marker='o', color='#4913ec')
        else:
            plt.plot([0], [0], marker='o')
        plt.ylim(0, 100)
        plt.xlabel('Question #')
        plt.ylabel('Score')
        plt.title('Interview Progress')
        plt.grid(alpha=0.2)
        plt.tight_layout()
        plt.savefig(line_chart_path, dpi=150)
        plt.close()
    except Exception as e:
        print(f"Chart generation error: {e}")

    # Paths for template (relative to /static)
    bar_chart_url = f"results/{bar_chart_filename}"
    line_chart_url = f"results/{line_chart_filename}"

    # Generate AI-based improvement suggestions and store in DB
    suggestions_text = ""
    try:
        # Summarize last answers for context
        sample_for_prompt = "\n".join([
            f"Q: {a['question']}\nA: {a['answer'][:500]}" for a in answers[-5:]
        ])
        prompt = (
            "Provide concise, actionable interview improvement suggestions in 4-6 bullet points based on these metrics and answers.\n"
            f"Metrics: score={score}, confidence={confidence}, grammar={grammar}, clarity={clarity}, tone={tone}, eye_contact={eye_contact}.\n"
            "Focus on delivery, structure, and specific practice tips.\n\n"
            f"Recent answers:\n{sample_for_prompt}"
        )
        ai_resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.5
        )
        suggestions_text = ai_resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq suggestion error: {e}")
        suggestions_text = "Practice structuring answers using STAR, add measurable outcomes, and rehearse aloud to improve confidence and clarity."

    try:
        db = get_db_connection()
        if db:
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO ai_feedback (user_id, suggestions) VALUES (%s, %s)",
                (session['user_id'], suggestions_text)
            )
            db.commit()
            cursor.close()
            db.close()
    except Exception as e:
        print(f"AI feedback DB error: {e}")

    # Generate feedback lists for UI
    if score >= 85:
        strengths = ["Excellent communication skills", "Strong technical knowledge", "Well-structured responses", "Good depth of answers"]
        improvements = ["Consider adding more specific metrics", "Practice advanced technical concepts"]
    elif score >= 70:
        strengths = ["Good communication skills", "Solid technical foundation", "Clear explanations"]
        improvements = ["Add more concrete examples", "Practice complex technical questions", "Work on confidence"]
    elif score >= 50:
        strengths = ["Basic technical understanding", "Willingness to engage"]
        improvements = ["Practice more technical questions", "Improve answer depth", "Work on communication clarity", "Study fundamental concepts"]
    else:
        strengths = ["Showed up for the interview", "Attempted all questions"]
        improvements = ["Need significant preparation", "Study core technical concepts", "Practice interview skills", "Work on communication"]

    return render_template(
        "result.html",
        score=score,
        confidence=confidence,
        grammar=grammar,
        clarity=clarity,
        breakdown=breakdown,
        tech_skills=tech_skills,
        strengths=strengths,
        improvements=improvements,
        answers=answers[-5:],
        total_questions=total_questions,
        bar_chart_url=bar_chart_url,
        line_chart_url=line_chart_url,
        ai_suggestions=suggestions_text
    )

# ----------------------
# Clear interview session
# ----------------------
@app.route("/clear_interview")
@login_required
def clear_interview():
    session.pop("questions", None)
    session.pop("current_question_index", None)
    session.pop("answers", None)
    session.pop("current_question", None)
    session.pop("total_questions", None)
    flash("Interview session cleared. You can start a new one.", "info")
    return redirect(url_for('dashboard'))

# ----------------------
# Logout
# ----------------------
@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for('login'))

@app.route("/api/questions")
@login_required
def get_questions():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    company = request.args.get("company")
    topic = request.args.get("topic")
    qtype = request.args.get("type")
    search = request.args.get("search")

    query = """
        SELECT q.id, q.title, q.description, q.type, q.views, q.likes, q.created_at,
               c.name as company_name, c.requirements as company_requirements,
               t.name as topic_name
        FROM questions q
        LEFT JOIN companies c ON q.company_id = c.id
        LEFT JOIN topics t ON q.topic_id = t.id
        WHERE 1=1
    """
    params = []

    if company and company != "all":
        query += " AND c.name=%s"
        params.append(company)
    if topic and topic != "all":
        query += " AND t.name=%s"
        params.append(topic)
    if qtype and qtype != "all":
        query += " AND q.type=%s"
        params.append(qtype)
    if search:
        query += " AND (q.title LIKE %s OR q.description LIKE %s OR c.name LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    query += " ORDER BY q.views DESC, q.likes DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    cursor.close()
    db.close()
    return jsonify(rows)

@app.route("/api/companies")
@login_required
def get_companies():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM companies ORDER BY name")
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(rows)

@app.route("/api/topics")
@login_required
def get_topics():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM topics ORDER BY name")
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify(rows)

@app.route("/api/question-types")
@login_required
def get_question_types():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT type FROM questions ORDER BY type")
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return jsonify([r["type"] for r in rows])

@app.route("/download_report")
@login_required
def download_report():
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import letter
    from flask import send_file

    # --- PDF output path (Windows-safe) ---
    pdf_path = os.path.join(app.root_path, "static", "results", f"report_{session['user_id']}.pdf")

    # Ensure folder exists
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    # --- Fetch values from session ---
    score = session.get("score", 0)
    confidence = session.get("confidence", 0)
    grammar = session.get("grammar", 0)
    clarity = session.get("clarity", 0)
    strengths = session.get("strengths", [])
    improvements = session.get("improvements", [])
    ai_suggestions = session.get("ai_suggestions", "No suggestions")

    # --- Document Setup ---
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Interview Performance Report", styles["Title"]))
    story.append(Spacer(1, 20))

    story.append(Paragraph(f"<b>Overall Score:</b> {score}%", styles["Normal"]))
    story.append(Paragraph(f"<b>Confidence:</b> {confidence}%", styles["Normal"]))
    story.append(Paragraph(f"<b>Grammar:</b> {grammar}%", styles["Normal"]))
    story.append(Paragraph(f"<b>Speech Clarity:</b> {clarity}%", styles["Normal"]))
    story.append(Spacer(1, 20))

    story.append(Paragraph("<b>Strengths</b>", styles["Heading2"]))
    for s in strengths:
        story.append(Paragraph(f"• {s}", styles["Normal"]))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>Areas for Improvement</b>", styles["Heading2"]))
    for imp in improvements:
        story.append(Paragraph(f"• {imp}", styles["Normal"]))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>AI Suggestions</b>", styles["Heading2"]))
    story.append(Paragraph(ai_suggestions.replace("\n", "<br/>"), styles["Normal"]))

    # Build PDF
    doc.build(story)

    # Serve file
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name="Interview_Report.pdf"
    )

@app.route("/interview_stopped")
@login_required
def interview_stopped():
    return render_template("interview_stopped.html")

# ----------------------
# Error handlers
# ----------------------
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# ----------------------
# Run app
# ----------------------
if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)