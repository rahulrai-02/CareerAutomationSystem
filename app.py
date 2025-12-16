import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import google.generativeai as genai
from fpdf import FPDF 

load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-777')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///job_automation.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads/resumes'
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- AI SETUP ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# --- DB SETUP ---
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_title = db.Column(db.String(100))
    mode = db.Column(db.String(50))
    content = db.Column(db.Text) # Added missing column
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

with app.app_context(): 
    db.create_all()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# --- 1. AUTHENTICATION ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        u, e, p = request.form.get('username'), request.form.get('email'), request.form.get('password')
        if User.query.filter_by(email=e).first():
            flash('Email already exists!', 'danger')
            return redirect(url_for('signup'))
        user = User(username=u, email=e); user.set_password(p)
        db.session.add(user); db.session.commit()
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('home_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- 2. DASHBOARDS ---
@app.route('/')
@login_required
def home_dashboard():
    apps = Application.query.filter_by(user_id=current_user.id).all()
    return render_template('home.html', user=current_user, applications=apps)
@app.route('/tracker')
@login_required
def tracker_dashboard():
    # Database se user ki sari activities fetch karega
    activities = Application.query.filter_by(user_id=current_user.id).order_by(Application.date_submitted.desc()).all()
    return render_template('tracker_dashboard.html', activities=activities)# --- 3. MNC PORTAL ---
@app.route('/mnc-portal')
@login_required
def mnc_portal():
    return render_template('mnc_portal.html')

# --- 4. RESUME STUDIO ---
@app.route('/resume-input')
@login_required
def input_form():
    return render_template('input.html')

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    data = {
        "personal": {
            "name": request.form.get("f_name"),
            "title": request.form.get("f_title"),
            "summary": request.form.get("f_summary")
        }
    }
    # Auto-save to DB
    new_app = Application(
        job_title=data['personal']['title'] or "Untitled Resume",
        mode="RESUME",
        content=f"Resume for {data['personal']['name']}. Summary: {data['personal']['summary']}",
        user_id=current_user.id
    )
    db.session.add(new_app); db.session.commit()
    return render_template('resume.html', d=data)

import google.generativeai as genai

@app.route('/analyzer', methods=['GET', 'POST'])
@login_required
def analyzer_input_form():
    analysis_result = None
    if request.method == 'POST':
        jd_text = request.form.get('jd_text')
        
        # The AI Prompt for Analysis
        prompt = f"""
        Analyze this Job Description as an expert HR Recruiter.
        Provide:
        1. TOP 5 KEYWORDS (for ATS optimization)
        2. TECHNICAL SKILLS REQUIRED
        3. SOFT SKILLS REQUIRED
        4. POTENTIAL INTERVIEW QUESTIONS
        
        Job Description: {jd_text}
        """
        
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            analysis_result = response.text
        except Exception as e:
            analysis_result = f"Error: {str(e)}"
            
    return render_template('analyzer_input.html', result=analysis_result)
@app.route('/email-tool')
@login_required
def mail_input_form():
    return render_template('mail_input.html')

@app.route('/generate_mail', methods=['POST'])
@login_required
def generate_mail():
    m_type = request.form.get('mail_type')
    job = request.form.get('job_title')
    sender = request.form.get('sender_name')
    receiver = request.form.get('receiver_name')
    
    content = f"Subject: Regarding {job}\n\nDear {receiver},\n\nThis is a {m_type} email from {sender}."
    
    # Save to Tracker
    new_mail = Application(job_title=f"Mail: {job}", mode="EMAIL", content=content, user_id=current_user.id)
    db.session.add(new_mail); db.session.commit()
    
    return render_template('mail_output.html', generated_email=content, mail_type=m_type)

@app.route('/upload-resume', methods=['POST'])
@login_required
def handle_resume_upload():
    if 'resume' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('mnc_portal'))
    
    file = request.files['resume']
    if file and allowed_file(file.filename):
        filename = secure_filename(f"user_{current_user.id}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        # Save to Tracker
        up = Application(job_title=file.filename, mode="UPLOAD", content="File Uploaded to Server", user_id=current_user.id)
        db.session.add(up); db.session.commit()
        
        flash('Resume uploaded!', 'success')
        return redirect(url_for('mnc_portal', uploaded='true'))
    return redirect(url_for('mnc_portal'))

@app.route('/download_resume', methods=['POST'])
@login_required
def download_resume():
    resume_text = request.form.get('resume_text')
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=11)
    clean_text = resume_text.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, txt=clean_text)
    return Response(pdf.output(dest='S'), mimetype="application/pdf", headers={"Content-disposition": "attachment; filename=Resume.pdf"})
import requests
from flask import render_template, request

@app.route('/jobs', methods=['GET', 'POST'])
def search_jobs():
    job_results = []
    if request.method == 'POST':
        role = request.form.get('query')
        location = request.form.get('location')
        
        # Your Adzuna Credentials
        APP_ID = "YOUR_APP_ID" # You still need the App ID from Adzuna dashboard
        API_KEY = "bbe2640cfb414890c130c6838322a513"
        
        # Adzuna API URL for India
        url = f"https://api.adzuna.com/v1/api/jobs/in/search/1?app_id={APP_ID}&app_key={API_KEY}&results_per_page=20&what={role}&where={location}&content-type=application/json"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                job_results = data.get('results', [])
        except Exception as e:
            print(f"Error fetching jobs: {e}")

    return render_template('jobs_dashboard.html', jobs=job_results)

if __name__ == '__main__':
    app.run(debug=True)