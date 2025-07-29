###########################################  imports 

from flask import Flask, request, render_template, redirect, url_for, session, send_from_directory, jsonify ,current_app
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, send, emit
import os
from flask_login import LoginManager, login_required, login_user, logout_user, current_user, UserMixin
from datetime import datetime
from werkzeug.utils import secure_filename
import random
from string import ascii_letters
from werkzeug.security import generate_password_hash, check_password_hash 

import redis
from sqlalchemy import text
from flask_migrate import Migrate
import requests
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_wtf import CSRFProtect

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))





########################################## initialize     

app = Flask(__name__)
csrf = CSRFProtect(app)
socketio = SocketIO(app)

# For local (no Docker)
# app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123456@localhost:5432/chatapp'
# app.config['SESSION_REDIS'] = redis.StrictRedis(host='localhost', port=6379, db=0)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'flask_session:'
app.config['SESSION_REDIS'] = redis.StrictRedis(
    host=os.environ['REDIS_HOST'],
    port=int(os.environ['REDIS_PORT']),
    db=0
)


Session(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


##################################################### helper 
UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'mp4', 'mp3', 'docx'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def generate_room_code(length: int, existing_codes: list[str]) -> str:
    while True:
        code_chars = [random.choice(ascii_letters) for _ in range(length)]
        code = ''.join(code_chars)

        if code not in existing_codes:
            return code
        

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    # use mime type check after upload

############################################  settings

AI_SERVICE_URL = os.environ.get("AI_SERVICE_URL")
app.config['AI_SERVICE_URL'] = AI_SERVICE_URL
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
# app.config['HUGGINGFACE_API_KEY'] = HUGGINGFACE_API_KEY





############################################# classes
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class PublicRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PrivateRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_type = db.Column(db.String(10))  # 'public' or 'private'
    room_id = db.Column(db.String(100))   # public: int, private: code
    sender = db.Column(db.String(100))
    message = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    with current_app.app_context():
        return db.session.get(User, user_id)





############################################# uploads 
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return {"error": "No file part"}, 400
    file = request.files['file']
    if file.filename == '':
        return {"error": "No selected file"}, 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        return {"message": "File uploaded", "file_url": f"/uploads/{filename}"}, 200
    return {"error": "File type not allowed"}, 400


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

############################################### login and signup
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            return render_template('signup.html', error="All fields are required.")
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template('signup.html', error="Username already exists.")
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            return render_template('login.html', error="Invalid credentials.")
        login_user(user)
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('home'))


############################################ AI chat endpoint
@csrf.exempt
@app.route("/ai_chat", methods=["POST"])
@limiter.limit("2 per minute")
def ai_chat():
    data = request.json
    user_message = data.get("message", "") if data else ""
    
    if not user_message:
                return jsonify({"error": "No message provided"}), 400
    try:
        response = requests.post(AI_SERVICE_URL, json={"message": user_message})
        result = response.json()
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500



##############################################  home routes
@app.route('/')
def home():
    public_rooms = PublicRoom.query.all()
    return render_template('home.html', public_rooms=public_rooms)

############################################### public rooms

@app.route('/create_public_room', methods=['POST'])
@login_required
def create_public_room():
    name = request.form.get('room_name')
    desc = request.form.get('description')
    if not name or not desc:
        return redirect(url_for('home'))
    existing = PublicRoom.query.filter_by(name=name).first()
    if existing:
        return redirect(url_for('home'))
    new_room = PublicRoom(name=name, description=desc, owner_id=current_user.id)
    db.session.add(new_room)
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/public_room/<int:room_id>')
@login_required
def join_public_room(room_id):
    room = PublicRoom.query.get_or_404(room_id)
    session['room'] = str(room_id)
    session['name'] = current_user.username
    messages = Message.query.filter_by(room_type='public', room_id=str(room_id)).all()
    serialized_msgs = [
    {'sender': msg.sender, 'content': msg.message, 'timestamp': str(msg.timestamp)}
    for msg in messages
    ]
    return render_template('public_chat.html', room=session['room'], user=session['name'], messages=serialized_msgs)
    
#################################################### private rooms

@app.route('/private', methods=["GET", "POST"])
def private_section():
    session.pop('room', None)
    session.pop('name', None)
    if request.method == "POST":
        name = request.form.get('name')
        create = request.form.get('create', False)
        code = request.form.get('code')
        join = request.form.get('join', False)

        if not name:
            return render_template('home.html', error="Name is required", code=code)

        if create != False:
            room_code = generate_room_code(6, [room.code for room in PrivateRoom.query.all()])
            new_room = PrivateRoom(code=room_code)
            db.session.add(new_room)
            db.session.commit()

        if join != False:
            if not code:
                return render_template('home.html', error="Please enter a room code to enter a chat room", name=name)
            private_room = PrivateRoom.query.filter_by(code=code).first()
            if not private_room:
                return render_template('home.html', error="Room code invalid", name=name)
            room_code = code

        session['room'] = room_code
        session['name'] = name
        return redirect(url_for('chat'))
    else:
        return render_template('private.html')

@app.route('/chat')
def chat():
    room = session.get('room')
    name = session.get('name')
    
    if name is None or room is None:
        return redirect(url_for('private_section'))

    if room.isnumeric():
        raw_messages = Message.query.filter_by(room_type='public', room_id=room).all()
    else:
        raw_messages = Message.query.filter_by(room_type='private', room_id=room).all()

    # 🛠️ Convert Message objects to dictionaries
    messages = [{
        "message": m.message,
        "sender": m.sender
    } for m in raw_messages]

    return render_template('chat.html', room=room, user=name, messages=messages)

################################################### testing

@app.route('/redis_test')
def redis_test():
    r = redis.Redis(host='localhost', port=6379, db=0)
    r.set('testkey', 'redis working')
    return r.get('testkey')

@app.route('/testpg')
def test_postgres():
    try:
        db.session.execute(text('SELECT 1'))
        return "PostgreSQL Connected 🟢"
    except Exception as e:
        return f"PostgreSQL Connection Error 🔴: {e}"



######################################### socketio events
# @socketio.on('join')

@socketio.on("join")
def handle_join(data):
    room = data["room"]
    join_room(room)
    socketio.emit("message", {
        "message": f"{data['username']} joined room",
        "sender": "",
        "is_system": True
    }, room=room)



@socketio.on('leave')
def handle_leave(data): 
    room = data.get('room')
    name = data.get('name')
    leave_room(room)
    send({"sender": "", "message": f"{name} has left the chat"}, to=room)

@socketio.on('send_file')
def handle_file(data):
    username = data.get("username", "Anonymous")
    file_url = data.get("file_url")
    if file_url:
        emit('receive_file', {"username": username, "file_url": file_url}, broadcast=True)

@socketio.on('message')
def handle_message(payload):
    room = session.get('room')
    name = session.get('name')
    msg_obj = {"sender": name, "message": payload["message"]}
    send(msg_obj, to=room)

    # Save to DB
    msg_db = Message(room_type='public' if room.isnumeric() else 'private',
                     room_id=room, sender=name, message=payload["message"])
    db.session.add(msg_db)
    db.session.commit()

@socketio.on('disconnect')
def handle_disconnect():
    room = session.get("room")
    name = session.get("name")
    leave_room(room)
    send({"message": f"{name} has left the chat", "sender": ""}, to=room)

########################################### main
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
    socketio.run(app, debug=True,host='0.0.0.0', port=8150)

# if __name__ == '__main__':
    
    
#     with app.app_context():
#         db.create_all()
#     socketio.run(app, debug=True, port=8150)



