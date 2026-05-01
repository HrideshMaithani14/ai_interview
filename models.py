from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    hobbies = db.Column(db.String(255), nullable=True)
    cv_text = db.Column(db.Text, nullable=True)
    job_requirement = db.Column(db.Text, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    domain = db.Column(db.String(50), nullable=True) # made nullable for signup step
    skill_level = db.Column(db.String(20), nullable=True) # made nullable for signup step
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    interviews = db.relationship('Interview', backref='user', lazy=True)
    roadmaps = db.relationship('Roadmap', backref='user', lazy=True)

class Interview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False) # In-Progress, Completed, Failed
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    
    rounds = db.relationship('Round', backref='interview', lazy=True)

class Round(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    interview_id = db.Column(db.Integer, db.ForeignKey('interview.id'), nullable=False)
    round_type = db.Column(db.Integer, nullable=False) # 1 (Coding), 2 (Quiz), 3 (Video), 4 (Antigravity)
    score = db.Column(db.Float)
    status = db.Column(db.String(20), nullable=False) # Passed, Failed, Pending
    feedback = db.Column(db.Text) # Detailed AI feedback
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Roadmap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False) # Markdown string of roadmap steps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
