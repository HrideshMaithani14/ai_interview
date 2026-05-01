import os
import subprocess
from dotenv import load_dotenv
import json
import PyPDF2
import docx
import google.generativeai as genai
from flask import Flask, render_template, redirect, url_for, flash, request, session
from flask_socketio import SocketIO, emit, join_room
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-123'
if os.environ.get('VERCEL') == '1':
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/database_v2.db'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database_v2.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

socketio = SocketIO(app, cors_allowed_origins="*")

import io

def extract_text_from_file(file):
    filename = file.filename.lower()
    text = ""
    try:
        if filename.endswith('.pdf'):
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif filename.endswith('.docx'):
            doc = docx.Document(file)
            for para in doc.paragraphs:
                text += para.text + "\n"
    except Exception as e:
        print(f"Error extracting text from {filename}: {e}")
    return text.strip()

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize DB
with app.app_context():
    db.create_all()
    
    # Seed Admin User
    admin_email = 'admin@Hardy'
    if not User.query.filter_by(email=admin_email).first():
        admin = User(
            email=admin_email,
            password_hash=generate_password_hash('AmericaJarvis'),
            name='Administrator',
            is_admin=True,
            domain='Admin',
            skill_level='Pro'
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin user seeded successfully.")

@app.route('/')
def index():
    if current_user.is_authenticated:
        if not current_user.domain or not current_user.skill_level:
            return redirect(url_for('profile'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('signup'))
            
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('profile'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            if not user.domain or not user.skill_level:
                return redirect(url_for('profile'))
            return redirect(url_for('dashboard'))
            
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form.get('name')
        current_user.hobbies = request.form.get('hobbies')
        current_user.domain = request.form.get('domain')
        current_user.skill_level = request.form.get('skill_level')
        current_user.job_requirement = request.form.get('job_requirement')
        
        cv_file = request.files.get('cv_file')
        if cv_file and cv_file.filename:
            current_user.cv_text = extract_text_from_file(cv_file)
            
        db.session.commit()
        flash('Professional profile configured. Welcome to your interview setup.', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('profile.html', user=current_user)

@app.route('/dashboard')
@login_required
def dashboard():
    from models import Interview, Round
    from datetime import datetime, timedelta
    
    interviews = Interview.query.filter_by(user_id=current_user.id).order_by(Interview.started_at.asc()).all()
    total_interviews = len(interviews)
    
    rounds = Round.query.join(Interview).filter(Interview.user_id == current_user.id, Round.score != None).all()
    avg_score = sum(r.score for r in rounds) / len(rounds) if rounds else 0
    
    # Calculate Time Spent (assume each round takes 5 minutes for now since ended_at isn't strictly tracked everywhere)
    time_spent_hours = round((len(rounds) * 5) / 60.0, 1)
    
    # Calculate Streak
    streak = 0
    if interviews:
        dates = sorted(list(set(i.started_at.date() for i in interviews)), reverse=True)
        current_date = datetime.utcnow().date()
        
        # Check if they interviewed today or yesterday to keep streak alive
        if dates and (current_date - dates[0]).days <= 1:
            streak = 1
            for i in range(1, len(dates)):
                if (dates[i-1] - dates[i]).days == 1:
                    streak += 1
                else:
                    break
    
    # Calculate Performance Trend (Today vs Yesterday)
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    
    today_rounds = [r for r in rounds if r.created_at.date() == today]
    yesterday_rounds = [r for r in rounds if r.created_at.date() == yesterday]
    
    today_avg = sum(r.score for r in today_rounds) / len(today_rounds) if today_rounds else None
    yesterday_avg = sum(r.score for r in yesterday_rounds) / len(yesterday_rounds) if yesterday_rounds else None
    
    trend_text = "🎯 Keep going to establish a trend!"
    trend_class = "text-muted"
    if today_avg is not None and yesterday_avg is not None:
        if yesterday_avg > 0:
            delta = ((today_avg - yesterday_avg) / yesterday_avg) * 100
            if delta > 0:
                trend_text = f"📈 +{round(delta, 1)}% from yesterday"
                trend_class = "text-success"
            elif delta < 0:
                trend_text = f"📉 {round(delta, 1)}% from yesterday"
                trend_class = "text-danger"
            else:
                trend_text = "➖ Same as yesterday"
                trend_class = "text-muted"
    
    # Radar Chart Data Calculation
    coding_scores = [r.score for r in rounds if r.round_type == 1]
    quiz_scores = [r.score for r in rounds if r.round_type == 2]
    ai_scores = [r.score for r in rounds if r.round_type == 3]
    antigravity_scores = [r.score for r in rounds if r.round_type == 4]

    radar_data = [
        sum(coding_scores)/len(coding_scores) if coding_scores else 0,
        sum(quiz_scores)/len(quiz_scores) if quiz_scores else 0,
        sum(ai_scores)/len(ai_scores) if ai_scores else 0,
        sum(antigravity_scores)/len(antigravity_scores) if antigravity_scores else 0
    ]
    
    return render_template('dashboard.html', 
                           user=current_user, 
                           total_interviews=total_interviews, 
                           avg_score=round(avg_score, 1),
                           streak=streak,
                           time_spent_hours=time_spent_hours,
                           trend_text=trend_text,
                           trend_class=trend_class,
                           radar_data=radar_data)



@app.route('/mentor')
@login_required
def mentor():
    from models import Roadmap
    roadmap = Roadmap.query.filter_by(user_id=current_user.id).order_by(Roadmap.created_at.desc()).first()
    return render_template('mentor.html', roadmap=roadmap)

@app.route('/api/mentor/generate', methods=['POST'])
@login_required
def generate_roadmap():
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        prompt = f"""You are an expert AI Career Mentor. 
Generate a comprehensive, step-by-step learning roadmap for a {current_user.skill_level} in {current_user.domain}.
Include specific technologies, concepts to master, and project ideas.
Format the output strictly in cleanly formatted Markdown."""
        response = model.generate_content(prompt)
        
        from models import Roadmap
        new_roadmap = Roadmap(user_id=current_user.id, content=response.text)
        db.session.add(new_roadmap)
        db.session.commit()
        return {'status': 'success'}
    except Exception as e:
        print("Mentor Error:", e)
        return {'status': 'error', 'message': str(e)}, 500

@app.route('/interview/start/<module_type>', methods=['POST'])
@login_required
def start_module(module_type):
    from models import Interview
    interview = Interview(user_id=current_user.id, status='In-Progress')
    db.session.add(interview)
    db.session.commit()
    
    if module_type == 'coding':
        return redirect(url_for('round1', interview_id=interview.id))
    elif module_type == 'quiz':
        return redirect(url_for('round2', interview_id=interview.id))
    elif module_type == 'ai':
        return redirect(url_for('round3', interview_id=interview.id))
    elif module_type == 'antigravity':
        return redirect(url_for('round4', interview_id=interview.id))
    elif module_type == 'design':
        return redirect(url_for('round5', interview_id=interview.id))
        
    return redirect(url_for('dashboard'))

@app.route('/interview/<int:interview_id>/round/3')
@login_required
def round3(interview_id):
    return render_template('round3.html', interview_id=interview_id)

@app.route('/interview/<int:interview_id>/round/4')
@login_required
def round4(interview_id):
    return render_template('antigravity.html', interview_id=interview_id)

@app.route('/api/interview/<int:interview_id>/round/4/generate', methods=['POST'])
@login_required
def generate_round4(interview_id):
    try:
        cv_file = request.files.get('cv')
        name = request.form.get('name')
        hobbies = request.form.get('hobbies')
        
        cv_text = ""
        if cv_file and cv_file.filename:
            cv_text = extract_text_from_file(cv_file)
            
        cv_snippet = cv_text[:3000] if cv_text else "No CV provided."
        
        model = genai.GenerativeModel('gemini-flash-latest')
        prompt = f"""You are an expert AI recruiter conducting an interview for {current_user.domain} at {current_user.skill_level} level.
Candidate Name: {name}
Hobbies: {hobbies}
CV Snippet: {cv_snippet}

Generate exactly 6 interview questions. The questions should be:
1. A personalized icebreaker based on their hobbies or background.
2. A question about their past experience from the CV.
3. A technical question for {current_user.domain}.
4. A scenario-based problem-solving question.
5. A question about a specific technology they listed.
6. A concluding question about their career goals.

Return ONLY a JSON array of 6 strings. No markdown blocks, no formatting. Example: ["Question 1", "Question 2", "Question 3", "Question 4", "Question 5", "Question 6"]"""
        
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        if text_response.startswith('```json'): text_response = text_response[7:]
        if text_response.startswith('```'): text_response = text_response[3:]
        if text_response.endswith('```'): text_response = text_response[:-3]
        
        questions = json.loads(text_response)
        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("Failed to parse valid questions list.")
            
        return {'questions': questions}
    except Exception as e:
        print("Round 4 Generate Error:", e)
        return {'error': str(e)}, 500

@app.route('/api/interview/<int:interview_id>/round/4/submit', methods=['POST'])
@login_required
def submit_round4(interview_id):
    try:
        data = request.json or {}
        qaPairs = data.get('qaPairs', [])
        
        if not qaPairs:
            return {'error': "No answers provided."}, 400
            
        qa_text = ""
        for i, pair in enumerate(qaPairs):
            qa_text += f"Q{i+1}: {pair.get('question')}\nA{i+1}: {pair.get('answer')}\n\n"
            
        model = genai.GenerativeModel('gemini-flash-latest')
        prompt = f"""You are an expert AI recruiter evaluating a candidate for {current_user.domain} ({current_user.skill_level}).
Here is the transcript of their interview:
{qa_text}

Evaluate their performance on a scale of 0 to 100 based on technical accuracy, communication skills, and problem-solving ability.
Return ONLY a JSON object exactly like this:
{{"score": 85, "feedback": "Your concise evaluation notes here."}}"""

        response = model.generate_content(prompt)
        text_response = response.text.strip()
        if text_response.startswith('```json'): text_response = text_response[7:]
        if text_response.startswith('```'): text_response = text_response[3:]
        if text_response.endswith('```'): text_response = text_response[:-3]
        
        result = json.loads(text_response)
        score = result.get('score', 0)
        feedback = result.get('feedback', 'No feedback provided.')
        
        status = 'Passed' if score >= 60 else 'Failed'
        
        from models import Round
        round_record = Round(interview_id=interview_id, round_type=4, score=score, status=status, feedback=feedback)
        db.session.add(round_record)
        db.session.commit()
        
        return {'status': status, 'score': score, 'feedback': feedback}
        
    except Exception as e:
        print("Round 4 Submit Error:", e)
        return {'error': str(e)}, 500

@app.route('/interview/<int:interview_id>/round/5')
@login_required
def round5(interview_id):
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        prompt = f"""You are an expert Software Architect. Generate a realistic System Design interview question for a candidate applying for {current_user.domain} at {current_user.skill_level} level.
The question should ask them to design a scalable system (e.g., Design Netflix, Design a URL Shortener) and mention the core requirements.
Return ONLY the problem statement text."""
        response = model.generate_content(prompt)
        question = response.text.strip()
    except Exception as e:
        print("Round 5 generation error:", e)
        question = "Design a highly available and scalable URL Shortening service (like bit.ly)."
    return render_template('round5.html', interview_id=interview_id, question=question)

@app.route('/api/interview/<int:interview_id>/round/5/submit', methods=['POST'])
@login_required
def submit_round5(interview_id):
    design_text = request.json.get('design', '')
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        prompt = f"""You are a strict Software Architect evaluating a System Design interview. 
The candidate submitted the following architecture description/diagram code:
{design_text}

Evaluate this design on a scale of 0 to 100 based on Scalability, Fault Tolerance, and appropriateness for a {current_user.skill_level} {current_user.domain} engineer.
Return ONLY a JSON object exactly like this:
{{"score": 85, "feedback": "Your evaluation notes here."}}"""
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        if text_response.startswith('```json'): text_response = text_response[7:]
        if text_response.startswith('```'): text_response = text_response[3:]
        if text_response.endswith('```'): text_response = text_response[:-3]
        result = json.loads(text_response)
        score = result.get('score', 0)
        feedback = result.get('feedback', 'No feedback provided.')
    except Exception as e:
        print("Round 5 evaluation error:", e)
        score = 0
        feedback = "Error evaluating your design."
        
    status = 'Passed' if score >= 60 else 'Failed'
    from models import Round
    round_record = Round(interview_id=interview_id, round_type=5, score=score, status=status, feedback=feedback)
    db.session.add(round_record)
    db.session.commit()
    
    return {'status': status, 'score': score, 'feedback': feedback}


@app.route('/interview/<int:interview_id>/round/1')
@login_required
def round1(interview_id):
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        cv_snippet = current_user.cv_text[:1000] if current_user.cv_text else "No CV provided."
        prompt = f"""You are an expert technical interviewer. Generate exactly one practical coding challenge for a candidate applying for {current_user.domain} at {current_user.skill_level} level.
Here is a snippet of their CV:
{cv_snippet}

Target Job Requirements:
{current_user.job_requirement or "No specific job requirements provided."}

Requirements:
- The challenge MUST be solvable in Python.
- Do NOT provide the solution.
- The output should be JUST the problem statement and requirements, no pleasantries.
- The challenge MUST specifically target the overlap between the candidate's CV and the Target Job Requirements."""
        
        response = model.generate_content(prompt)
        question = response.text.strip()
    except Exception as e:
        print("Round 1 generation error:", e)
        question = "Write a Python function named 'reverse_string' that takes a string as input and returns the reversed string."
        
    return render_template('round1.html', interview_id=interview_id, question=question)

@app.route('/api/interview/<int:interview_id>/round/1/submit', methods=['POST'])
@login_required
def submit_round1(interview_id):
    code = request.json.get('code', '')
    
    # Very basic execution for dev purposes
    test_code = code + "\n\nassert reverse_string('hello') == 'olleh', 'Test Failed'\nprint('Test Passed')"
    
    try:
        result = subprocess.run(['python', '-c', test_code], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            status = 'Passed'
            output = result.stdout
        else:
            status = 'Failed'
            output = result.stderr
    except subprocess.TimeoutExpired:
        status = 'Failed'
        output = 'Execution Timed Out'
    except Exception as e:
        status = 'Failed'
        output = str(e)
        
    from models import Round
    round_record = Round(interview_id=interview_id, round_type=1, score=100 if status == 'Passed' else 0, status=status)
    db.session.add(round_record)
    db.session.commit()
        
    return {'status': status, 'output': output}

@app.route('/interview/<int:interview_id>/round/2')
@login_required
def round2(interview_id):
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        cv_snippet = current_user.cv_text[:3000] if current_user.cv_text else "No CV provided."
        prompt = f"""You are an expert technical interviewer. Generate exactly 50 random multiple-choice questions for a candidate applying for {current_user.domain} at {current_user.skill_level} level.
Here is a snippet of their CV:
{cv_snippet}

Target Job Requirements:
{current_user.job_requirement or "No specific job requirements provided."}

The questions MUST:
1. Evaluate the candidate's applicability for the Target Job Requirements based entirely on the technologies and experiences listed in their CV.
2. Be completely unique (do not repeat any questions or concepts).
3. Include a mix of technical depth and relevant aptitude.
Return the output strictly as a JSON array of 50 objects, with each object having 'id' (int), 'text' (string), 'options' (array of 4 strings), and 'answer' (the exact string of the correct option). Do not use markdown blocks or formatting."""
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        if text_response.startswith('```json'): text_response = text_response[7:]
        if text_response.startswith('```'): text_response = text_response[3:]
        if text_response.endswith('```'): text_response = text_response[:-3]
        questions_data = json.loads(text_response)
        
        # Save correct answers to session
        correct_answers = {str(q['id']): q['answer'] for q in questions_data}
        session['round2_answers'] = correct_answers
        
        # Pass questions without answer to frontend
        questions = [{"id": q['id'], "text": q['text'], "options": q['options']} for q in questions_data]
    except Exception as e:
        print("Round 2 error:", e)
        questions = [
            {"id": 1, "text": "What is the time complexity of binary search?", "options": ["O(1)", "O(n)", "O(log n)", "O(n^2)"]},
            {"id": 2, "text": "Which data structure uses LIFO?", "options": ["Queue", "Stack", "Tree", "Graph"]}
        ]
        session['round2_answers'] = {'1': 'O(log n)', '2': 'Stack'}
        
    return render_template('round2.html', interview_id=interview_id, questions=questions)

@app.route('/api/interview/<int:interview_id>/round/2/submit', methods=['POST'])
@login_required
def submit_round2(interview_id):
    answers = request.json.get('answers', {})
    correct_answers = session.get('round2_answers', {})
    
    correct = 0
    total = len(correct_answers) if correct_answers else 2
    for q_id, correct_ans in correct_answers.items():
        if answers.get(q_id) == correct_ans:
            correct += 1
            
    score = (correct / total) * 100 if total > 0 else 0
    status = 'Passed' if score >= 50 else 'Failed'
    
    from models import Round
    round_record = Round(interview_id=interview_id, round_type=2, score=score, status=status)
    db.session.add(round_record)
    db.session.commit()
    
    return {'status': status, 'score': score}

@app.route('/api/interview/<int:interview_id>/round/3/interact', methods=['POST'])
@login_required
def interact_round3(interview_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        user_message = data.get('message', '')
        
        try:
            model = genai.GenerativeModel('gemini-flash-latest')
            cv_snippet = current_user.cv_text[:2000] if current_user.cv_text else "No CV provided."
            system_prompt = f"""You are an expert technical interviewer conducting a mock video interview.
The candidate's name is {current_user.name}. 
Their domain is {current_user.domain} and their skill level is {current_user.skill_level}.
Here is their CV:
{cv_snippet}

Target Job Requirements:
{current_user.job_requirement or "No specific job requirements provided."}

Keep your responses VERY concise (1-2 sentences max). Speak naturally as if in a live verbal conversation.
Interview flow:
1. Break the ice by welcoming them, using their name, and asking a personal or introductory question strictly related to their CV or professional background (do NOT ask about hobbies).
2. Present a verbal technical or coding scenario relevant to their domain to assess their problem-solving skills.
3. Ask deep technical questions based strictly on the overlap between their CV and the Job Requirements.
4. Conclude the interview when appropriate.

Respond directly to the candidate's message below, evaluate their answer briefly, and immediately ask the next question in the flow.
Candidate says: '{user_message}'"""

            response = model.generate_content(system_prompt)
            ai_reply = response.text
        except Exception as e:
            ai_reply = "I am having trouble connecting to my brain right now."
            print("Gemini Error:", e)
            
        return {'reply': ai_reply.replace('*', '')}
    except Exception as overall_e:
        print("Server Error in interact_round3:", overall_e)
        return {'reply': f"Backend Server Error: {str(overall_e)}"}, 500

@app.route('/api/interview/<int:interview_id>/round/3/submit', methods=['POST'])
@login_required
def submit_round3(interview_id):
    data = request.json or {}
    score = data.get('confidence_score', 0)
    
    status = 'Passed' if score >= 50 else 'Failed'
    feedback = "Good eye contact and positive expressions." if score >= 50 else "Try to maintain more positive expressions and steady eye contact."
    
    from models import Round
    round_record = Round(interview_id=interview_id, round_type=3, score=score, status=status, feedback=feedback)
    db.session.add(round_record)
    db.session.commit()
    
    return {'status': status, 'score': score}

# Admin Routes
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Unauthorized access', 'error')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    from models import Interview, Round
    from datetime import datetime, timedelta
    
    interviews = Interview.query.all()
    rounds = Round.query.all()
    
    # Calculate Weekly Leaderboard
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    weekly_rounds = Round.query.filter(Round.created_at >= one_week_ago, Round.score != None).all()
    
    user_scores = {}
    for r in weekly_rounds:
        user_id = r.interview.user_id
        if user_id not in user_scores:
            user_scores[user_id] = []
        user_scores[user_id].append(r.score)
        
    leaderboard = []
    for user_id, scores in user_scores.items():
        user = User.query.get(user_id)
        if not user.is_admin:
            avg = sum(scores) / len(scores)
            leaderboard.append({'user': user, 'avg_score': round(avg, 1), 'tests_taken': len(scores)})
            
    leaderboard.sort(key=lambda x: x['avg_score'], reverse=True)
    
    return render_template('admin_dashboard.html', users=users, interviews=interviews, rounds=rounds, leaderboard=leaderboard)

@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('index'))

# WebSocket for Live Camera
@socketio.on('video_frame')
def handle_video_frame(data):
    # Broadcast frame to the admin room
    emit('video_frame_broadcast', {'image': data.get('image'), 'user_id': data.get('user_id'), 'name': data.get('name')}, to='admin_room')

@socketio.on('join_admin')
def on_join_admin():
    join_room('admin_room')

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)
