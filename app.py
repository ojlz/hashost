import os
import re
import secrets
import json
import io
import time
import random
import hashlib
import threading
import subprocess
from datetime import datetime, timedelta

import bcrypt
import bleach
import filetype
from flask import (
    Flask, request, send_from_directory, abort, session,
    render_template, redirect, url_for, jsonify
)
from PIL import Image
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Auto-update on startup
# ---------------------------------------------------------------------------
def auto_update():
    try:
        repo = os.path.join(os.path.expanduser('~'), 'hashost')
        if os.path.isdir(os.path.join(repo, '.git')):
            subprocess.run(
                ['git', '-C', repo, 'pull', 'origin', 'master'],
                capture_output=True, timeout=15
            )
    except Exception:
        pass

auto_update()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY_FILE = '.secret_key'

def get_secret_key():
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, 'r') as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, 'w') as f:
        f.write(key)
    return key

app.secret_key = os.environ.get("SECRET_KEY") or get_secret_key()

UPLOAD_FOLDER = 'uploads'
HASHBIN_FOLDER = 'hashbin_data'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(HASHBIN_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024

DOMAIN = os.environ.get("DOMAIN", "https://hashost.pythonanywhere.com")
RATE_LIMIT_SECONDS = 5
INVITE_RATE_LIMIT = 5

ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
    'video/mp4', 'video/webm', 'audio/mpeg', 'video/mov', 'audio/ogg'
}
ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    '.mp4', '.webm', '.mp3', '.mov', '.ogg'
}
DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.com', '.scr', '.pif', '.vbs', '.js', '.jar',
    '.php', '.asp', '.jsp', '.sh', '.py', '.pl', '.rb', '.html', '.htm', '.svg'
}
VIDEO_EXTENSIONS = ('.mp4', '.webm', '.avi', '.mov')

FILE_LIFETIME_OPTIONS = [
    {'value': '1h', 'label': '1 hora', 'seconds': 3600},
    {'value': '3d', 'label': '3 dias', 'seconds': 259200},
    {'value': '1w', 'label': '1 semana', 'seconds': 604800},
    {'value': '1M', 'label': '1 mês', 'seconds': 2592000},
    {'value': '0', 'label': 'Permanente', 'seconds': 0},
]

RANDOM_UPLOAD_TITLES = [
    "Imagem subiu, servidor caiu🤣🔥📸",
    "Funciona até parar de funcionar",
    "HH, Upload rápido, manutenção lenta.",
    "🔥 Upload subiu. Temperatura também.",
    "😎 Rodando em hardware que pediu aposentadoria.",
    "Se o servidor cair, finja que está em manutenção.",
    "📸 Hospedando imagens e arrependimentos.",
    "HashHost, Enviando pixels na força do ódio 🤳",
    "Se funcionar, não mexe.",
    "😎 Feito com Flask e decisões ruins.",
    "Hospedagem premium de procedência duvidosa.",
    "🤑 Infraestrutura avaliada em um pastel e uma coca.",
    "A imagem carrega, normalmente...",
    "Mais um pixel no infinito.",
    "Upload concluído antes que o café esfrie.",
    "Isso é arte? O servidor acha que sim.",
    "Salvo. Pelo menos por agora.",
    "Transferido com fé e ping alto.",
]

RANDOM_HASHBIN_TITLES = [
    "📝 Seu bug agora é público.",
    "Armazenando código que nem o autor entende.",
    "☎️ Este texto sobreviverá mais que seu projeto.",
    "Cole aqui e finja que está documentado.",
    "100% livre de organização.",
    "Hash, aqui nascem as gambiarras.",
    "Código temporário, consequências permanentes.",
    "Nem o Ctrl+Z salva isso.",
    "Copiado, colado, rezado.",
    "Funciona no meu computador™.",
    "Estilo Gambiarra™.",
    "Código feio, mas funciona.",
    "Aposto que ninguém vai ler isso aqui.",
    "Isso aqui é arte abstrata.",
    "Se deletar, suma com provas.",
    "Bug disfarçado de feature.",
    "Gambiarra level: production.",
    "Isso é documentação? Não, é arte.",
]

DEFAULT_PERMISSIONS = {
    'is_admin': False,
    'is_team': False,
    'can_create_invites': False,
    'invite_count': 0,
    'file_lifetime': ['0'],
    'can_change_title': True,
    'can_use_hashbin': False,
    'hashbin_lifetime': ['0'],
    'can_change_password': True,
    'can_choose_embed_color': True,
}

MINIMAL_PERMISSIONS = {
    'is_admin': False,
    'is_team': False,
    'can_create_invites': False,
    'invite_count': 0,
    'file_lifetime': ['0'],
    'can_change_title': False,
    'can_use_hashbin': False,
    'hashbin_lifetime': ['0'],
    'can_change_password': False,
    'can_choose_embed_color': False,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_json(file, default=None):
    if default is None:
        default = {}
    try:
        with open(file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password, hashed):
    if hashed.startswith('$2'):
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    return hashlib.sha256(password.encode('utf-8')).hexdigest() == hashed


def upgrade_password(username, password):
    users = load_users()
    if username in users:
        users[username]['password_hash'] = hash_password(password)
        save_json('users.json', users)


def load_users():
    users = load_json('users.json')
    if not users:
        users = {
            "admin": {
                "password_hash": hash_password("admin123"),
                "created": datetime.now().isoformat(),
                "uploads": 0,
                "status": "approved",
                "permissions": {
                    "is_admin": True,
                    "is_team": True,
                    "can_create_invites": True,
                    "invite_count": -1,
                    "file_lifetime": ["0"],
                    "can_change_title": True,
                    "can_use_hashbin": True,
                    "hashbin_lifetime": ["0"],
                    "can_change_password": True,
                    "can_choose_embed_color": True,
                },
                "profile": {}
            }
        }
        save_json('users.json', users)
    else:
        migrated = False
        for username, user in users.items():
            if 'status' not in user:
                user['status'] = 'approved'
                migrated = True
            if 'permissions' not in user:
                user['permissions'] = DEFAULT_PERMISSIONS.copy()
                migrated = True
            if 'uploads' not in user:
                user['uploads'] = 0
                migrated = True
            if 'is_team' not in user.get('permissions', {}):
                user.setdefault('permissions', {}).update({'is_team': False})
                migrated = True
            if 'profile' not in user:
                user['profile'] = {}
                migrated = True
        if migrated:
            save_json('users.json', users)
    return users


def sanitize_text(text):
    clean = bleach.clean(str(text or ""), tags=[], strip=True)
    return clean.replace('<', '').replace('>', '').replace('"', '').replace("'", '').replace('&', '')[:200]


COLOR_REGEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def is_valid_color(color):
    return bool(COLOR_REGEX.match(color))


WEAK_PASSWORDS = [
    '123456', '123456789', '12345678', '1234567', '12345',
    'password', 'senha', 'admin', 'qwerty', 'abc123',
    '111111', '000000', 'iloveyou', 'letmein', 'welcome',
]

def is_weak_password(password):
    lower = password.lower()
    if lower in WEAK_PASSWORDS:
        return True
    if re.search(r'(.)\1{2,}', lower):
        return True
    if re.search(r'(012|123|234|345|456|567|678|789|890|987|876|765|654|543|432|321|210)', lower):
        return True
    if password.isdigit():
        return True
    if len(password) > 8 and len(set(password)) <= 3:
        return True
    return False


USERNAME_REGEX = re.compile(r'^[a-zA-Z0-9_]{3,16}$')

def is_valid_username(username):
    return bool(USERNAME_REGEX.match(username))


def check_rate_limit(username):
    rate_limits = load_json('rate_limits.json')
    if username in rate_limits:
        elapsed = time.time() - rate_limits[username]['last_upload']
        if elapsed < RATE_LIMIT_SECONDS:
            wait = int(RATE_LIMIT_SECONDS - elapsed)
            return False, "Aguarde %d segundos" % wait
    return True, "OK"


def update_rate_limit(username):
    rate_limits = load_json('rate_limits.json')
    rate_limits[username] = {
        'last_upload': time.time(),
        'uploads_count': rate_limits.get(username, {}).get('uploads_count', 0) + 1
    }
    save_json('rate_limits.json', rate_limits)


def check_invite_rate_limit(ip):
    rate_limits = load_json('invite_rate_limits.json')
    now = time.time()
    if ip in rate_limits:
        attempts = [t for t in rate_limits[ip] if now - t < 60]
        rate_limits[ip] = attempts
        if len(attempts) >= INVITE_RATE_LIMIT:
            return False
        rate_limits[ip].append(now)
    else:
        rate_limits[ip] = [now]
    save_json('invite_rate_limits.json', rate_limits)
    return True


def is_safe_file(file_content, filename, allow_video=False):
    ext = os.path.splitext(filename)[1].lower()

    if ext in DANGEROUS_EXTENSIONS:
        return False, "Tipo de arquivo perigoso"
    if ext in VIDEO_EXTENSIONS and not allow_video:
        return False, "Upload de vídeos não autorizado"
    if ext not in ALLOWED_EXTENSIONS:
        return False, "Extensão não permitida: %s" % ext

    max_size = 100 * 1024 * 1024 if allow_video else 20 * 1024 * 1024
    if len(file_content) < 100:
        return False, "Mídia muito pequena"
    if len(file_content) > max_size:
        return False, "Mídia muito grande (máximo %dMB)" % (max_size // 1024 // 1024)

    try:
        kind = filetype.guess(file_content)
        mime_type = kind.mime if kind else None
        if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
            return False, "MIME não permitido: %s" % mime_type
        if ext not in VIDEO_EXTENSIONS:
            img = Image.open(io.BytesIO(file_content))
            img.verify()
    except Exception as e:
        return False, "Mídia inválida: %s" % str(e)

    lower = file_content.lower()
    for pattern in [b'<script', b'javascript:', b'vbscript:', b'onload=', b'onerror=']:
        if pattern in lower:
            return False, "Conteúdo suspeito"

    return True, "OK"


def get_media_dimensions(filepath):
    try:
        if filepath.lower().endswith(VIDEO_EXTENSIONS):
            return (1200, 675)
        with Image.open(filepath) as img:
            return img.size
    except Exception:
        return (1200, 630)


def is_admin_user():
    return (
        'username' in session
        and load_users().get(session['username'], {})
        .get('permissions', {}).get('is_admin', False)
    )


def is_approved():
    if 'username' not in session:
        return False
    users = load_users()
    user = users.get(session['username'], {})
    return user.get('status') == 'approved'


def is_approved_user(users, username):
    user = users.get(username, {})
    return user.get('status') == 'approved'


def get_user_perms(username):
    users = load_users()
    user = users.get(username, {})
    return user.get('permissions', DEFAULT_PERMISSIONS.copy())


def generate_invite_code():
    return secrets.token_urlsafe(24)


def cleanup_expired_files():
    try:
        short_urls = load_json('short_urls.json')
        now = datetime.now()
        to_remove = []
        for short_id, data in short_urls.items():
            if data.get('expire_at'):
                if datetime.fromisoformat(data['expire_at']) < now:
                    filepath = os.path.join(UPLOAD_FOLDER, data['filename'])
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    to_remove.append(short_id)
        for short_id in to_remove:
            del short_urls[short_id]
        if to_remove:
            save_json('short_urls.json', short_urls)
    except Exception as e:
            print("Erro na limpeza de mídias: %s" % e)


def cleanup_expired_pastes():
    try:
        pastes = load_json('pastes.json')
        now = datetime.now()
        to_remove = []
        for paste_id, data in pastes.items():
            if data.get('expires'):
                if datetime.fromisoformat(data['expires']) < now:
                    paste_file = os.path.join(HASHBIN_FOLDER, '%s.txt' % paste_id)
                    if os.path.exists(paste_file):
                        os.remove(paste_file)
                    to_remove.append(paste_id)
        for paste_id in to_remove:
            del pastes[paste_id]
        if to_remove:
            save_json('pastes.json', pastes)
    except Exception as e:
        print("Erro na limpeza de pastes: %s" % e)


def schedule_cleanup():
    cleanup_expired_files()
    cleanup_expired_pastes()
    threading.Timer(300, schedule_cleanup).start()

schedule_cleanup()


# ---------------------------------------------------------------------------
# Routes — Public
# ---------------------------------------------------------------------------
@app.route('/')
def landing():
    if 'username' in session:
        return redirect(url_for('index'))
    return render_template('landing.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = sanitize_text(request.form.get('username', '').strip())
        password = request.form.get('password', '')
        if not username or not password:
            return render_template('login.html', error="Usuário e senha obrigatórios")
        users = load_users()
        if username in users and check_password(password, users[username]['password_hash']):
            user = users[username]
            if user.get('status') == 'pending':
                return render_template('login.html', error="Sua conta está pendente de aprovação")
            if user.get('status') == 'rejected':
                return render_template('login.html', error="Sua conta foi rejeitada")
            if not user['password_hash'].startswith('$2'):
                upgrade_password(username, password)
            session['username'] = username
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=24)
            return redirect(url_for('index'))
        return render_template('login.html', error="Usuário ou senha incorretos")
    return render_template('login.html')


@app.route('/iv/<code>')
def invite_page(code):
    ip = request.remote_addr
    if not check_invite_rate_limit(ip):
        return render_template('message.html', type='error',
                               message="Muitas tentativas. Aguarde 1 minuto.",
                               back_url='/', back_text='Voltar')
    invites = load_json('invites.json')
    if code not in invites:
        return render_template('message.html', type='error',
                               message="Convite inválido.",
                               back_url='/', back_text='Voltar')
    invite = invites[code]
    if invite.get('used'):
        return render_template('message.html', type='error',
                               message="Este convite já foi utilizado.",
                               back_url='/', back_text='Voltar')
    if invite.get('expires'):
        if datetime.fromisoformat(invite['expires']) < datetime.now():
            return render_template('message.html', type='error',
                                   message="Este convite expirou.",
                                   back_url='/', back_text='Voltar')
    return render_template('signup.html', invite_code=code,
                           inviter=invite.get('created_by', ''))


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = sanitize_text(request.form.get('username', '').strip())
        password = request.form.get('password', '')
        invite_code = sanitize_text(request.form.get('invite_code', '').strip())

        if not username or not password:
            return render_template('signup.html', error="Usuário e senha são obrigatórios",
                                   invite_code=invite_code)
        if not is_valid_username(username):
            return render_template('signup.html', error="Usuário deve ter 3-16 caracteres (letras, números, _)",
                                   invite_code=invite_code)
        if len(password) < 6 or len(password) > 32:
            return render_template('signup.html', error="Senha deve ter entre 6 e 32 caracteres",
                                   invite_code=invite_code)
        if is_weak_password(password):
            return render_template('signup.html', error="Senha fraca. Escolha uma senha mais segura",
                                   invite_code=invite_code)

        users = load_users()
        if username in users:
            return render_template('signup.html', error="Usuário já existe",
                                   invite_code=invite_code)

        if invite_code:
            invites = load_json('invites.json')
            if invite_code not in invites:
                return render_template('signup.html', error="Código de invite inválido",
                                       invite_code=invite_code)
            invite = invites[invite_code]
            if invite.get('used'):
                return render_template('signup.html', error="Invite já foi utilizado",
                                       invite_code=invite_code)
            max_uses = invite.get('max_uses', 1)
            use_count = invite.get('use_count', 0)
            if max_uses > 0 and use_count >= max_uses:
                return render_template('signup.html', error="Invite atingiu o limite de usos",
                                       invite_code=invite_code)
            if invite.get('expires'):
                if datetime.fromisoformat(invite['expires']) < datetime.now():
                    return render_template('signup.html', error="Invite expirado",
                                           invite_code=invite_code)

            invite_perms = invites[invite_code].get('permissions')
            if invite_perms:
                user_permissions = invite_perms.copy()
            else:
                user_permissions = MINIMAL_PERMISSIONS.copy()

            users[username] = {
                'password_hash': hash_password(password),
                'created': datetime.now().isoformat(),
                'uploads': 0,
                'status': 'approved',
                'permissions': user_permissions,
                'profile': {},
            }
            invites[invite_code]['use_count'] = invites[invite_code].get('use_count', 0) + 1
            max_uses = invites[invite_code].get('max_uses', 1)
            if max_uses > 0 and invites[invite_code]['use_count'] >= max_uses:
                invites[invite_code]['used'] = True
            invites[invite_code]['used_by'] = username
            save_json('invites.json', invites)
            save_json('users.json', users)
            session['username'] = username
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=24)
            return redirect(url_for('index'))
        else:
            users[username] = {
                'password_hash': hash_password(password),
                'created': datetime.now().isoformat(),
                'uploads': 0,
                'status': 'pending',
                'permissions': DEFAULT_PERMISSIONS.copy(),
                'profile': {},
            }
            save_json('users.json', users)
            return render_template('signup_success.html')

    return render_template('signup.html', invite_code=request.args.get('invite', ''))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------
@app.route('/dashboard')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not is_approved():
        session.clear()
        return redirect(url_for('login'))
    users = load_users()
    user = users.get(session['username'], {})
    perms = user.get('permissions', {})
    return render_template(
        'dashboard.html',
        username=session['username'],
        is_admin=perms.get('is_admin', False),
        can_change_password=perms.get('can_change_password', False),
        can_choose_embed_color=perms.get('can_choose_embed_color', False),
        can_change_title=perms.get('can_change_title', True),
        can_use_hashbin=perms.get('can_use_hashbin', False),
        can_create_invites=perms.get('can_create_invites', False),
        file_lifetime_options=FILE_LIFETIME_OPTIONS,
        allowed_lifetimes=perms.get('file_lifetime', ['0']),
    )


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return abort(401, "Não autorizado")
    if not is_approved():
        return abort(403, "Conta não aprovada")

    username = session['username']
    can_upload, message = check_rate_limit(username)
    if not can_upload:
        return abort(429, message)

    if 'file' not in request.files or request.files['file'].filename == '':
        return "Erro: Nenhuma mídia enviada", 400

    file = request.files['file']
    file_content = file.read()
    filename = file.filename

    users = load_users()
    user = users.get(username, {})
    perms = user.get('permissions', {})

    is_safe, error_msg = is_safe_file(file_content, filename, allow_video=True)
    if not is_safe:
        return "Mídia rejeitada: %s" % error_msg, 400

    title = sanitize_text(request.form.get('title', '').strip()) or random.choice(RANDOM_UPLOAD_TITLES)
    description = request.form.get('description', '').strip() or ''
    embed_color = request.form.get('embed_color', '#0070f3')
    file_lifetime = request.form.get('file_lifetime', '0')

    if not is_valid_color(embed_color):
        embed_color = '#0070f3'

    if not perms.get('can_change_title', True):
        title = random.choice(RANDOM_UPLOAD_TITLES)

    if not perms.get('can_choose_embed_color', True):
        embed_color = '#0070f3'

    allowed_lifetimes = perms.get('file_lifetime', ['0'])
    if file_lifetime not in allowed_lifetimes:
        file_lifetime = allowed_lifetimes[0] if allowed_lifetimes else '0'

    ext = os.path.splitext(secure_filename(filename))[1].lower()
    random_name = secrets.token_hex(16) + ext
    filepath = os.path.join(UPLOAD_FOLDER, random_name)

    with open(filepath, 'wb') as f:
        f.write(file_content)
    try:
        os.chmod(filepath, 0o644)
    except OSError:
        pass

    short_urls = load_json('short_urls.json')
    short_id = secrets.token_urlsafe(8)
    while short_id in short_urls:
        short_id = secrets.token_urlsafe(8)

    expire_seconds = 0
    for opt in FILE_LIFETIME_OPTIONS:
        if opt['value'] == file_lifetime:
            expire_seconds = opt['seconds']
            break

    expire_at = None
    if expire_seconds > 0:
        expire_at = (datetime.now() + timedelta(seconds=expire_seconds)).isoformat()

    short_urls[short_id] = {
        'filename': random_name,
        'original_filename': filename,
        'title': title,
        'description': description,
        'username': username,
        'upload_time': datetime.now().isoformat(),
        'views': 0,
        'embed_color': embed_color,
        'file_size': len(file_content),
        'expire_at': expire_at,
        'file_lifetime': file_lifetime,
    }
    save_json('short_urls.json', short_urls)

    update_rate_limit(username)
    users = load_users()
    users[username]['uploads'] = users[username].get('uploads', 0) + 1
    save_json('users.json', users)

    return "Upload concluído: %s/s/%s" % (DOMAIN, short_id)


# ---------------------------------------------------------------------------
# Routes — API Upload (para ShareX, etc)
# ---------------------------------------------------------------------------
def get_or_create_api_token(username):
    users = load_users()
    user = users.get(username, {})
    token = user.get('api_token', '')
    if not token:
        token = secrets.token_urlsafe(32)
        users[username]['api_token'] = token
        save_json('users.json', users)
    return token


def get_user_by_api_token(token):
    if not token:
        return None
    users = load_users()
    for uname, udata in users.items():
        if udata.get('api_token') == token:
            return uname
    return None


@app.route('/api/upload', methods=['POST'])
def api_upload():
    auth = request.headers.get('Authorization', '')
    token = ''
    if auth.startswith('Bearer '):
        token = auth[7:].strip()
    if not token:
        token = request.form.get('api_token', '').strip()
    if not token:
        return jsonify({'error': 'Token de API necessário'}), 401

    username = get_user_by_api_token(token)
    if not username:
        return jsonify({'error': 'Token inválido'}), 401

    users = load_users()
    user = users.get(username, {})
    perms = user.get('permissions', {})

    if not is_approved_user(users, username):
        return jsonify({'error': 'Conta não aprovada'}), 403

    can_upload, message = check_rate_limit(username)
    if not can_upload:
        return jsonify({'error': message}), 429

    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({'error': 'Nenhuma mídia enviada'}), 400

    file = request.files['file']
    file_content = file.read()
    filename = file.filename

    is_safe, error_msg = is_safe_file(file_content, filename, allow_video=True)
    if not is_safe:
        return jsonify({'error': 'Mídia rejeitada: %s' % error_msg}), 400

    title = sanitize_text(request.form.get('title', '').strip()) or random.choice(RANDOM_UPLOAD_TITLES)
    description = request.form.get('description', '').strip() or ''
    embed_color = request.form.get('embed_color', '#0070f3')
    file_lifetime = request.form.get('file_lifetime', '0')

    if not is_valid_color(embed_color):
        embed_color = '#0070f3'
    if not perms.get('can_change_title', True):
        title = random.choice(RANDOM_UPLOAD_TITLES)
    if not perms.get('can_choose_embed_color', True):
        embed_color = '#0070f3'

    allowed_lifetimes = perms.get('file_lifetime', ['0'])
    if file_lifetime not in allowed_lifetimes:
        file_lifetime = allowed_lifetimes[0] if allowed_lifetimes else '0'

    ext = os.path.splitext(secure_filename(filename))[1].lower()
    random_name = secrets.token_hex(16) + ext
    filepath = os.path.join(UPLOAD_FOLDER, random_name)

    with open(filepath, 'wb') as f:
        f.write(file_content)
    try:
        os.chmod(filepath, 0o644)
    except OSError:
        pass

    expire_seconds = 0
    for opt in FILE_LIFETIME_OPTIONS:
        if opt['value'] == file_lifetime:
            expire_seconds = opt['seconds']
            break

    expire_at = None
    if expire_seconds > 0:
        expire_at = (datetime.now() + timedelta(seconds=expire_seconds)).isoformat()

    short_urls = load_json('short_urls.json')
    short_id = secrets.token_urlsafe(8)
    while short_id in short_urls:
        short_id = secrets.token_urlsafe(8)

    short_urls[short_id] = {
        'filename': random_name,
        'original_filename': filename,
        'title': title,
        'description': description,
        'username': username,
        'upload_time': datetime.now().isoformat(),
        'views': 0,
        'embed_color': embed_color,
        'file_size': len(file_content),
        'expire_at': expire_at,
        'file_lifetime': file_lifetime,
    }
    save_json('short_urls.json', short_urls)

    update_rate_limit(username)
    users = load_users()
    users[username]['uploads'] = users[username].get('uploads', 0) + 1
    save_json('users.json', users)

    return jsonify({
        'url': '%s/s/%s' % (DOMAIN, short_id),
        'page': '%s/s/%s' % (DOMAIN, short_id),
        'raw': '%s/s/%s/raw' % (DOMAIN, short_id),
        'short_id': short_id,
    })


# ---------------------------------------------------------------------------
# Routes — Shared files
# ---------------------------------------------------------------------------
@app.route('/s/<path:short_id>')
def short_url(short_id):
    parts = short_id.split('/')
    actual_id = parts[0]
    suffix = parts[1] if len(parts) > 1 else None

    short_urls = load_json('short_urls.json')
    if actual_id not in short_urls:
        return abort(404, "URL não encontrada")

    data = short_urls[actual_id]

    if data.get('expire_at'):
        if datetime.fromisoformat(data['expire_at']) < datetime.now():
            filepath = os.path.join(UPLOAD_FOLDER, data['filename'])
            if os.path.exists(filepath):
                os.remove(filepath)
            del short_urls[actual_id]
            save_json('short_urls.json', short_urls)
            return abort(404, "Mídia expirada")

    filepath = os.path.join(UPLOAD_FOLDER, data['filename'])
    if not os.path.exists(filepath):
        return abort(404, "Mídia não encontrada")

    short_urls[actual_id]['views'] = data.get('views', 0) + 1
    save_json('short_urls.json', short_urls)

    if suffix == 'raw':
        return send_from_directory(UPLOAD_FOLDER, data['filename'])
    if suffix == 'info':
        return _build_info_page(data, actual_id)
    return _build_embed_page(data, actual_id, filepath)


def _build_info_page(data, actual_id):
    upload_date = datetime.fromisoformat(data['upload_time']).strftime('%d/%m/%Y às %H:%M')
    file_size = "%.2f MB" % (data.get('file_size', 0) / 1024 / 1024)
    is_video = data['filename'].lower().endswith(VIDEO_EXTENSIONS)
    uploader = load_users().get(data.get('username', ''), {})
    profile = uploader.get('profile', {})
    profile_color = profile.get('color', '')
    embed_color = data.get('embed_color', '#0070f3')
    if profile_color and is_valid_color(profile_color):
        embed_color = profile_color
    proxy_url = "%s/proxy/%s" % (DOMAIN, data['filename'])

    if is_video:
        media_html = (
            '<video controls src="%s" '
            'style="max-width:300px;max-height:200px;border-radius:8px;'
            'border:1px solid var(--border)"></video>' % proxy_url
        )
    else:
        media_html = (
            '<img src="%s" alt="%s" '
            'style="max-width:300px;max-height:200px;border-radius:8px;'
            'border:1px solid var(--border)">' % (proxy_url, data['title'])
        )

    return render_template(
        'info.html',
        title=data['title'],
        embed_color=embed_color,
        short_id=actual_id,
        media_html=media_html,
        original_filename=data['original_filename'],
        username=data['username'],
        upload_date=upload_date,
        file_size=file_size,
        views=data.get('views', 0),
        file_type=data['filename'].split('.')[-1].upper(),
        embed_author=profile.get('embed_author', ''),
        embed_author_url=profile.get('embed_author_url', ''),
        embed_footer=profile.get('embed_footer', ''),
        avatar_url=profile.get('avatar_url', ''),
        display_name=profile.get('display_name', ''),
    )


def _build_embed_page(data, actual_id, filepath):
    width, height = get_media_dimensions(filepath)
    if width < 400 or height < 300:
        width, height = max(width, 400), max(height, 300)

    is_video = data['filename'].lower().endswith(VIDEO_EXTENSIONS)
    uploader = load_users().get(data.get('username', ''), {})
    profile = uploader.get('profile', {})
    profile_color = profile.get('color', '')
    embed_color = data.get('embed_color', '#0070f3')
    if profile_color and is_valid_color(profile_color):
        embed_color = profile_color
    proxy_url = "%s/proxy/%s" % (DOMAIN, data['filename'])

    if is_video:
        media_html = (
            '<video controls style="max-width:100%%;height:auto;'
            'border:1px solid #333;border-radius:8px" src="%s"></video>' % proxy_url
        )
    else:
        media_html = (
            '<img src="%s" alt="%s" '
            'style="max-width:100%%;height:auto;border:1px solid #333;'
            'border-radius:8px">' % (proxy_url, data['title'])
        )

    info_link = "%s/s/%s/info" % (DOMAIN, actual_id)
    raw_link = "%s/s/%s/raw" % (DOMAIN, actual_id)
    page_url = "%s/s/%s" % (DOMAIN, actual_id)

    html = render_template(
        'embed.html',
        title=data['title'],
        description=data['description'],
        proxy_url=proxy_url,
        width=width,
        height=height,
        embed_color=embed_color,
        media_html=media_html,
        info_link=info_link,
        raw_link=raw_link,
        page_url=page_url,
        embed_author=profile.get('embed_author', ''),
        embed_author_url=profile.get('embed_author_url', ''),
        embed_footer=profile.get('embed_footer', ''),
        avatar_url=profile.get('avatar_url', ''),
        display_name=profile.get('display_name', ''),
    )

    response = app.response_class(html, 200, mimetype='text/html; charset=utf-8')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@app.route('/proxy/<filename>')
def proxy_image(filename):
    filename = secure_filename(filename)
    if not os.path.exists(os.path.join(UPLOAD_FOLDER, filename)):
        return abort(404)
    response = send_from_directory(UPLOAD_FOLDER, filename)
    response.headers['Cache-Control'] = 'public, max-age=3600'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ---------------------------------------------------------------------------
# Routes — HashBin
# ---------------------------------------------------------------------------
@app.route('/hashbin')
def hashbin():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not is_approved():
        return abort(403, "Conta não aprovada")
    perms = get_user_perms(session['username'])
    if not perms.get('can_use_hashbin', False):
        return abort(403, "Sem permissão para usar HashBin")
    return render_template('hashbin.html')


@app.route('/hashbin/create', methods=['POST'])
def hashbin_create():
    if 'username' not in session:
        return jsonify({'error': 'Não autorizado'})
    if not is_approved():
        return jsonify({'error': 'Conta não aprovada'})
    perms = get_user_perms(session['username'])
    if not perms.get('can_use_hashbin', False):
        return jsonify({'error': 'Sem permissão para usar HashBin'})

    content = request.form.get('content', '').strip()
    title = sanitize_text(request.form.get('title', '').strip()) or random.choice(RANDOM_HASHBIN_TITLES)
    syntax = request.form.get('syntax', 'text')
    try:
        expiry = int(request.form.get('expiry', 0) or 0)
    except (ValueError, TypeError):
        expiry = 0

    if not content:
        return jsonify({'error': 'Conteúdo é obrigatório'})
    if len(content.encode('utf-8')) > 30 * 1024 * 1024:
        return jsonify({'error': 'Conteúdo muito grande (máximo 30MB)'})

    allowed_lifetimes = perms.get('hashbin_lifetime', ['0'])
    if str(expiry) not in allowed_lifetimes and expiry != 0:
        expiry = 0

    paste_id = secrets.token_urlsafe(10)
    paste_file = os.path.join(HASHBIN_FOLDER, '%s.txt' % paste_id)
    with open(paste_file, 'w', encoding='utf-8') as f:
        f.write(content)

    pastes = load_json('pastes.json')
    expire_time = (datetime.now() + timedelta(hours=expiry)).isoformat() if expiry > 0 else None
    pastes[paste_id] = {
        'title': title,
        'syntax': syntax,
        'created': datetime.now().isoformat(),
        'expires': expire_time,
        'views': 0,
        'size': len(content.encode('utf-8')),
        'username': session['username'],
    }
    save_json('pastes.json', pastes)
    return jsonify({'success': True, 'paste_url': "%s/p/%s" % (DOMAIN, paste_id)})


@app.route('/p/<paste_id>')
def view_paste(paste_id):
    pastes = load_json('pastes.json')
    if paste_id not in pastes:
        return abort(404, "Paste não encontrado")

    paste_data = pastes[paste_id]

    if paste_data.get('expires'):
        expire_time = datetime.fromisoformat(paste_data['expires'])
        if datetime.now() > expire_time:
            paste_file = os.path.join(HASHBIN_FOLDER, '%s.txt' % paste_id)
            if os.path.exists(paste_file):
                os.remove(paste_file)
            del pastes[paste_id]
            save_json('pastes.json', pastes)
            return abort(404, "Paste expirado")

    pastes[paste_id]['views'] = paste_data.get('views', 0) + 1
    save_json('pastes.json', pastes)

    paste_file = os.path.join(HASHBIN_FOLDER, '%s.txt' % paste_id)
    try:
        with open(paste_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return abort(404, "Mídia não encontrada")

    created_date = datetime.fromisoformat(paste_data['created']).strftime('%d/%m/%Y às %H:%M')
    expires_text = (
        "Nunca" if not paste_data.get('expires')
        else datetime.fromisoformat(paste_data['expires']).strftime('%d/%m/%Y às %H:%M')
    )
    safe_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    return render_template(
        'paste_view.html',
        title=paste_data['title'],
        paste_id=paste_id,
        created_date=created_date,
        syntax=paste_data['syntax'].title(),
        views=paste_data.get('views', 0),
        size_kb=paste_data.get('size', 0) // 1024,
        expires_text=expires_text,
        safe_content=safe_content,
    )


@app.route('/p/<paste_id>/raw')
def view_paste_raw(paste_id):
    pastes = load_json('pastes.json')
    if paste_id not in pastes:
        return abort(404, "Paste não encontrado")
    paste_file = os.path.join(HASHBIN_FOLDER, '%s.txt' % paste_id)
    try:
        with open(paste_file, 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except FileNotFoundError:
        return abort(404, "Mídia não encontrada")


# ---------------------------------------------------------------------------
# Routes — Account Settings
# ---------------------------------------------------------------------------
@app.route('/account', methods=['GET', 'POST'])
def account():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not is_approved():
        session.clear()
        return redirect(url_for('login'))

    username = session['username']
    users = load_users()
    user = users.get(username, {})
    perms = user.get('permissions', {})
    error = None
    success = None

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'change_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not perms.get('can_change_password', False):
                error = "Sem permissão para alterar senha"
            elif not current_password or not new_password or not confirm_password:
                error = "Todos os campos são obrigatórios"
            elif not check_password(current_password, user['password_hash']):
                error = "Senha atual incorreta"
            elif new_password != confirm_password:
                error = "Senhas não coincidem"
            elif len(new_password) < 6:
                error = "Nova senha deve ter pelo menos 6 caracteres"
            else:
                users[username]['password_hash'] = hash_password(new_password)
                save_json('users.json', users)
                success = "Senha alterada com sucesso"

        elif action == 'generate_invite':
            if not perms.get('can_create_invites', False):
                error = "Você não tem permissão para criar convites"
            else:
                invite_count = perms.get('invite_count', 0)
                if invite_count == 0:
                    error = "Limite de invites atingido"
                else:
                    invites = load_json('invites.json')
                    code = generate_invite_code()
                    while code in invites:
                        code = generate_invite_code()
                    max_uses = int(request.form.get('max_uses', 1) or 1)
                    invites[code] = {
                        'created_by': username,
                        'created_at': datetime.now().isoformat(),
                        'used': False,
                        'used_by': None,
                        'expires': None,
                        'permissions': None,
                        'max_uses': max_uses,
                        'use_count': 0,
                    }
                    save_json('invites.json', invites)
                    if invite_count > 0:
                        users[username]['permissions']['invite_count'] = max(0, invite_count - 1)
                        save_json('users.json', users)
                    success = "Convite criado"

        elif action == 'delete_invite':
            code = request.form.get('code', '')
            invites = load_json('invites.json')
            if code in invites and invites[code].get('created_by') == username:
                del invites[code]
                save_json('invites.json', invites)
                success = "Convite removido"

        elif action == 'delete_file':
            short_id = request.form.get('short_id', '')
            short_urls = load_json('short_urls.json')
            if short_id in short_urls and short_urls[short_id].get('username') == username:
                filepath = os.path.join(UPLOAD_FOLDER, short_urls[short_id]['filename'])
                if os.path.exists(filepath):
                    os.remove(filepath)
                del short_urls[short_id]
                save_json('short_urls.json', short_urls)
                users = load_users()
                users[username]['uploads'] = max(0, users[username].get('uploads', 0) - 1)
                save_json('users.json', users)
                success = "Mídia removida"

        elif action == 'update_profile':
            if not perms.get('is_team', False) and not perms.get('is_admin', False):
                error = "Sem permissão para personalizar perfil"
            else:
                profile = users[username].get('profile', {})
                profile['display_name'] = sanitize_text(request.form.get('display_name', '').strip())
                profile['avatar_url'] = sanitize_text(request.form.get('avatar_url', '').strip())
                profile['color'] = request.form.get('color', '#0070f3')
                profile['embed_author'] = sanitize_text(request.form.get('embed_author', '').strip())
                profile['embed_author_url'] = sanitize_text(request.form.get('embed_author_url', '').strip())
                profile['embed_footer'] = sanitize_text(request.form.get('embed_footer', '').strip())
                if not is_valid_color(profile['color']):
                    profile['color'] = '#0070f3'
                users[username]['profile'] = profile
                save_json('users.json', users)
                success = "Perfil atualizado com sucesso"

        elif action == 'regenerate_token':
            users[username]['api_token'] = secrets.token_urlsafe(32)
            save_json('users.json', users)
            success = "Token regenerado com sucesso"

        users = load_users()
        user = users.get(username, {})
        perms = user.get('permissions', {})

    invites = load_json('invites.json')
    user_invites = {k: v for k, v in invites.items() if v.get('created_by') == username}

    short_urls = load_json('short_urls.json')
    user_files = []
    for sid, data in short_urls.items():
        if data.get('username') == username:
            user_files.append({
                'short_id': sid,
                'title': data.get('title', 'Mídia'),
                'original_filename': data.get('original_filename', ''),
                'upload_time': data.get('upload_time', ''),
                'views': data.get('views', 0),
                'expire_at': data.get('expire_at'),
            })
    user_files.sort(key=lambda x: x['upload_time'], reverse=True)

    return render_template(
        'account.html',
        username=username,
        perms=perms,
        profile=user.get('profile', {}),
        api_token=get_or_create_api_token(username),
        invites=user_invites,
        user_files=user_files,
        DOMAIN=DOMAIN,
        error=error,
        success=success,
    )


# ---------------------------------------------------------------------------
# Routes — Change Password (redirects to account)
# ---------------------------------------------------------------------------
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    return redirect(url_for('account'))


# ---------------------------------------------------------------------------
# Routes — Admin
# ---------------------------------------------------------------------------
@app.route('/admin')
def admin_panel():
    if not is_admin_user():
        return abort(403, "Acesso negado")

    users = load_users()
    short_urls = load_json('short_urls.json')
    invites = load_json('invites.json')

    total_size = 0
    user_stats = {}
    for data in short_urls.values():
        fp = os.path.join(UPLOAD_FOLDER, data['filename'])
        if os.path.exists(fp):
            total_size += os.path.getsize(fp)
        u = data['username']
        if u not in user_stats:
            user_stats[u] = {'uploads': 0, 'size': 0}
        user_stats[u]['uploads'] += 1
        user_stats[u]['size'] += data.get('file_size', 0)

    top_users = sorted(user_stats.items(), key=lambda x: x[1]['uploads'], reverse=True)[:10]
    total_views = sum(d.get('views', 0) for d in short_urls.values())

    pending_users = {u: d for u, d in users.items() if d.get('status') == 'pending'}
    approved_users = {u: d for u, d in users.items() if d.get('status') == 'approved'}

    top_users_data = [
        {'username': u, 'uploads': d['uploads'], 'size_mb': d['size'] // 1024 // 1024}
        for u, d in top_users
    ]

    return render_template(
        'admin.html',
        pending_users=pending_users,
        approved_users=approved_users,
        total_files=len(short_urls),
        total_users=len(approved_users),
        total_size_mb=total_size // 1024 // 1024,
        total_views=total_views,
        top_users=top_users_data,
        invites=invites,
    )


@app.route('/admin/approve_user/<username>', methods=['POST'])
def approve_user(username):
    if not is_admin_user():
        return abort(403, "Acesso negado")
    users = load_users()
    if username in users:
        users[username]['status'] = 'approved'
        save_json('users.json', users)
    return redirect('/admin')


@app.route('/admin/reject_user/<username>', methods=['POST'])
def reject_user(username):
    if not is_admin_user():
        return abort(403, "Acesso negado")
    users = load_users()
    if username in users:
        users[username]['status'] = 'rejected'
        save_json('users.json', users)
    return redirect('/admin')


@app.route('/admin/delete_user/<username>', methods=['POST'])
def delete_user(username):
    if not is_admin_user():
        return abort(403, "Acesso negado")
    users = load_users()
    if username in users and username != session.get('username'):
        del users[username]
        save_json('users.json', users)
    return redirect('/admin')


@app.route('/admin/create_user', methods=['GET', 'POST'])
def create_user():
    if not is_admin_user():
        return abort(403, "Acesso negado")

    error = None

    if request.method == 'POST':
        new_username = sanitize_text(request.form.get('username', '').strip())
        new_password = request.form.get('password', '').strip()

        if not new_username or not new_password:
            error = "Usuário e senha são obrigatórios."
        elif not is_valid_username(new_username):
            error = "Usuário deve ter 3-16 caracteres (letras, números, _)."
        elif len(new_password) < 6 or len(new_password) > 32:
            error = "Senha deve ter entre 6 e 32 caracteres."
        elif is_weak_password(new_password):
            error = "Senha fraca. Escolha uma senha mais segura."
        else:
            users = load_users()
            if new_username in users:
                error = "Usuário já existe."

        if error:
            return render_template('create_user.html', error=error, file_lifetime_options=FILE_LIFETIME_OPTIONS)

        is_admin_perm = 'is_admin' in request.form
        is_team_perm = 'is_team' in request.form
        can_create_invites = 'can_create_invites' in request.form
        invite_count = int(request.form.get('invite_count', 0) or 0)
        can_change_title = 'can_change_title' in request.form
        can_use_hashbin = 'can_use_hashbin' in request.form
        can_change_password = 'can_change_password' in request.form
        can_choose_embed_color = 'can_choose_embed_color' in request.form

        file_lifetime = request.form.getlist('file_lifetime') or ['0']
        hashbin_lifetime = request.form.getlist('hashbin_lifetime') or ['0']

        if is_admin_perm:
            permissions = {
                'is_admin': True,
                'is_team': True,
                'can_create_invites': True,
                'invite_count': -1,
                'file_lifetime': ['0'],
                'can_change_title': True,
                'can_use_hashbin': True,
                'hashbin_lifetime': ['0'],
                'can_change_password': True,
                'can_choose_embed_color': True,
            }
        else:
            permissions = {
                'is_admin': False,
                'is_team': is_team_perm,
                'can_create_invites': can_create_invites,
                'invite_count': invite_count if can_create_invites else 0,
                'file_lifetime': file_lifetime,
                'can_change_title': can_change_title,
                'can_use_hashbin': can_use_hashbin,
                'hashbin_lifetime': hashbin_lifetime if can_use_hashbin else ['0'],
                'can_change_password': can_change_password,
                'can_choose_embed_color': can_choose_embed_color,
            }

        users[new_username] = {
            'password_hash': hash_password(new_password),
            'created': datetime.now().isoformat(),
            'uploads': 0,
            'status': 'approved',
            'permissions': permissions,
            'profile': {},
        }
        save_json('users.json', users)

        return render_template('message.html', type='success',
                               message="Usuário '%s' criado com sucesso." % new_username,
                               back_url='/admin', back_text='Voltar ao admin')

    return render_template('create_user.html', file_lifetime_options=FILE_LIFETIME_OPTIONS)


@app.route('/admin/edit_user/<username>', methods=['GET', 'POST'])
def edit_user(username):
    if not is_admin_user():
        return abort(403, "Acesso negado")
    users = load_users()
    if username not in users:
        return redirect('/admin')

    error = None
    success = None

    if request.method == 'POST':
        is_admin_perm = request.form.get('is_admin') == '1'
        is_team_perm = request.form.get('is_team') == '1'
        can_create_invites = request.form.get('can_create_invites') == '1'
        invite_count = int(request.form.get('invite_count', 0) or 0)
        can_change_title = request.form.get('can_change_title') == '1'
        can_use_hashbin = request.form.get('can_use_hashbin') == '1'
        can_change_password = request.form.get('can_change_password') == '1'
        can_choose_embed_color = request.form.get('can_choose_embed_color') == '1'
        file_lifetime = request.form.getlist('file_lifetime') or ['0']
        hashbin_lifetime = request.form.getlist('hashbin_lifetime') or ['0']

        if is_admin_perm:
            permissions = {
                'is_admin': True, 'is_team': True, 'can_create_invites': True, 'invite_count': -1,
                'file_lifetime': ['0'], 'can_change_title': True, 'can_use_hashbin': True,
                'hashbin_lifetime': ['0'], 'can_change_password': True, 'can_choose_embed_color': True,
            }
        else:
            permissions = {
                'is_admin': False, 'is_team': is_team_perm, 'can_create_invites': can_create_invites,
                'invite_count': invite_count if can_create_invites else 0,
                'file_lifetime': file_lifetime, 'can_change_title': can_change_title,
                'can_use_hashbin': can_use_hashbin,
                'hashbin_lifetime': hashbin_lifetime if can_use_hashbin else ['0'],
                'can_change_password': can_change_password,
                'can_choose_embed_color': can_choose_embed_color,
            }

        users[username]['permissions'] = permissions
        save_json('users.json', users)
        success = "Permissões atualizadas com sucesso"

    return render_template(
        'edit_user.html',
        username=username,
        user=users[username],
        file_lifetime_options=FILE_LIFETIME_OPTIONS,
        error=error,
        success=success,
    )


@app.route('/admin/generate_invite', methods=['POST'])
def generate_invite():
    if not is_admin_user():
        return jsonify({'error': 'Sem permissão'})

    users = load_users()
    admin_user = users.get(session['username'], {})
    admin_perms = admin_user.get('permissions', {})

    if admin_perms.get('invite_count', 0) == 0:
        return jsonify({'error': 'Limite de invites atingido'})

    count = int(request.form.get('count', 1) or 1)
    max_count = admin_perms.get('invite_count', 0)
    if max_count > 0:
        count = min(count, max_count)

    max_uses = int(request.form.get('max_uses', 1) or 1)

    invites = load_json('invites.json')
    created = []

    for _ in range(count):
        code = generate_invite_code()
        while code in invites:
            code = generate_invite_code()
        invites[code] = {
            'created_by': session['username'],
            'created_at': datetime.now().isoformat(),
            'used': False,
            'used_by': None,
            'expires': None,
            'permissions': None,
            'max_uses': max_uses,
            'use_count': 0,
        }
        created.append(code)

    if max_count > 0:
        users[session['username']]['permissions']['invite_count'] = max(0, max_count - count)

    save_json('invites.json', invites)
    save_json('users.json', users)
    return jsonify({'success': True, 'invites': created})


@app.route('/admin/delete_invite/<code>', methods=['POST'])
def delete_invite(code):
    if not is_admin_user():
        return abort(403, "Acesso negado")
    invites = load_json('invites.json')
    if code in invites:
        del invites[code]
        save_json('invites.json', invites)
    return redirect('/admin')


# ---------------------------------------------------------------------------
# Routes — Deploy
# ---------------------------------------------------------------------------
DEPLOY_TOKEN = os.environ.get("DEPLOY_TOKEN", "hashhost-deploy-2024")

@app.route('/deploy', methods=['POST'])
def deploy_webhook():
    token = request.headers.get('X-Deploy-Token') or request.args.get('token')
    if token != DEPLOY_TOKEN:
        return abort(403, "Token inválido")
    try:
        home = os.path.expanduser('~')
        subprocess.Popen(
            ['bash', '-c', 'cd %s && git pull origin master && pip3 install --user -r requirements.txt' % home],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return jsonify({'status': 'deploy iniciado'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=False)
