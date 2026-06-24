import os
import secrets
import json
import io
import time
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
TOOLS_FOLDER = 'tools_data'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TOOLS_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024

DOMAIN = os.environ.get("DOMAIN", "https://hashost.pythonanywhere.com")
RATE_LIMIT_SECONDS = 5

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
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov'}

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
                "permissions": {
                    "change_password": True,
                    "upload_videos": True,
                    "custom_urls": True,
                    "is_admin": True,
                    "choose_embed_color": True,
                    "permanent_files": True,
                    "file_lifetime": 0,
                }
            }
        }
        save_json('users.json', users)
    return users


def sanitize_text(text):
    clean = bleach.clean(str(text or ""), tags=[], strip=True)
    return clean.replace('<', '').replace('>', '').replace('"', '').replace("'", '').replace('&', '')[:200]


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


def is_safe_file(file_content, filename, allow_video=False):
    ext = os.path.splitext(filename)[1].lower()

    if ext in DANGEROUS_EXTENSIONS:
        return False, "Tipo de arquivo perigoso"
    if ext in VIDEO_EXTENSIONS and not allow_video:
        return False, "Upload de videos nao autorizado"
    if ext not in ALLOWED_EXTENSIONS:
        return False, "Extensao nao permitida: %s" % ext

    max_size = 100 * 1024 * 1024 if allow_video else 20 * 1024 * 1024
    if len(file_content) < 100:
        return False, "Arquivo muito pequeno"
    if len(file_content) > max_size:
        return False, "Arquivo muito grande (maximo %dMB)" % (max_size // 1024 // 1024)

    try:
        kind = filetype.guess(file_content)
        mime_type = kind.mime if kind else None
        if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
            return False, "MIME nao permitido: %s" % mime_type
        if ext not in VIDEO_EXTENSIONS:
            img = Image.open(io.BytesIO(file_content))
            img.verify()
    except Exception as e:
        return False, "Arquivo invalido: %s" % str(e)

    lower = file_content.lower()
    for pattern in [b'<script', b'javascript:', b'vbscript:', b'onload=', b'onerror=']:
        if pattern in lower:
            return False, "Conteudo suspeito"

    return True, "OK"


def get_media_dimensions(filepath):
    try:
        if filepath.lower().endswith(VIDEO_EXTENSIONS):
            return (1200, 675)
        with Image.open(filepath) as img:
            return img.size
    except Exception:
        return (1200, 630)


def is_admin():
    return (
        'username' in session
        and load_users().get(session['username'], {})
        .get('permissions', {}).get('is_admin', False)
    )


def cleanup_anonymous_files():
    try:
        short_urls = load_json('short_urls.json')
        now = datetime.now()
        to_remove = []
        for short_id, data in short_urls.items():
            if data.get('anonymous', False):
                upload_time = datetime.fromisoformat(data['upload_time'])
                if (now - upload_time).total_seconds() > 1200:
                    filepath = os.path.join(UPLOAD_FOLDER, data['filename'])
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    to_remove.append(short_id)
        for short_id in to_remove:
            del short_urls[short_id]
        if to_remove:
            save_json('short_urls.json', short_urls)
    except Exception as e:
        print("Erro na limpeza: %s" % e)


def schedule_cleanup():
    cleanup_anonymous_files()
    threading.Timer(300, schedule_cleanup).start()

schedule_cleanup()

# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    users = load_users()
    user = users.get(session['username'], {})
    perms = user.get('permissions', {})
    return render_template(
        'dashboard.html',
        username=session['username'],
        is_admin=perms.get('is_admin', False),
        can_change_password=perms.get('change_password', False),
        can_custom_url=perms.get('custom_urls', False),
        can_choose_embed_color=perms.get('choose_embed_color', False),
    )


@app.route('/anonymous')
def anonymous():
    return render_template(
        'dashboard.html',
        username='anonimo',
        is_admin=False,
        can_change_password=False,
        can_custom_url=False,
        can_choose_embed_color=False,
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = sanitize_text(request.form.get('username', '').strip())
        password = request.form.get('password', '')
        if not username or not password:
            return render_template('login.html', error="Usuario e senha obrigatorios")
        users = load_users()
        if username in users and check_password(password, users[username]['password_hash']):
            if not users[username]['password_hash'].startswith('$2'):
                upgrade_password(username, password)
            session['username'] = username
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=24)
            return redirect(url_for('index'))
        return render_template('login.html', error="Usuario ou senha incorretos")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'username' not in session:
        return abort(401, "Nao autorizado")
    users = load_users()
    user = users.get(session['username'], {})
    if not user.get('permissions', {}).get('change_password', False):
        return abort(403, "Sem permissao para alterar senha")

    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_password or not new_password or not confirm_password:
            return render_template('message.html', type='error',
                                   message="Todos os campos sao obrigatorios.",
                                   back_url='/change_password', back_text='Tentar novamente')
        if not check_password(current_password, user['password_hash']):
            return render_template('message.html', type='error',
                                   message="Senha atual incorreta.",
                                   back_url='/change_password', back_text='Tentar novamente')
        if new_password != confirm_password:
            return render_template('message.html', type='error',
                                   message="Senhas nao coincidem.",
                                   back_url='/change_password', back_text='Tentar novamente')
        if len(new_password) < 6:
            return render_template('message.html', type='error',
                                   message="Nova senha deve ter pelo menos 6 caracteres.",
                                   back_url='/change_password', back_text='Tentar novamente')

        users[session['username']]['password_hash'] = hash_password(new_password)
        save_json('users.json', users)
        return render_template('message.html', type='success',
                               message="Senha alterada com sucesso.",
                               back_url='/', back_text='Voltar ao painel')

    return render_template('change_password.html')


# ---------------------------------------------------------------------------
# Routes — Upload
# ---------------------------------------------------------------------------
@app.route('/upload', methods=['POST'])
def upload_file():
    username = session.get('username', 'anonymous')
    is_logged = 'username' in session

    if is_logged:
        can_upload, message = check_rate_limit(username)
        if not can_upload:
            return abort(429, message)

    if 'file' not in request.files or request.files['file'].filename == '':
        return "Erro: Nenhum arquivo enviado", 400

    file = request.files['file']
    file_content = file.read()
    filename = file.filename

    allow_video = False
    if is_logged:
        users = load_users()
        user = users.get(username, {})
        allow_video = user.get('permissions', {}).get('upload_videos', False)

    is_safe, error_msg = is_safe_file(file_content, filename, allow_video)
    if not is_safe:
        return "Arquivo rejeitado: %s" % error_msg, 400

    title = request.form.get('title', '').strip() or 'Arquivo'
    description = request.form.get('description', '').strip() or ''
    embed_color = request.form.get('embed_color', '#0070f3') if is_logged else '#0070f3'
    custom_url = request.form.get('custom_url', '').strip() if is_logged else ''

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

    if custom_url and is_logged:
        users = load_users()
        user = users.get(username, {})
        if user.get('permissions', {}).get('custom_urls', False):
            if custom_url in short_urls:
                os.remove(filepath)
                return "Erro: URL personalizada ja existe", 400
            short_id = custom_url
        else:
            short_id = secrets.token_urlsafe(8)
    else:
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
        'anonymous': not is_logged,
        'file_size': len(file_content),
    }
    save_json('short_urls.json', short_urls)

    if is_logged:
        update_rate_limit(username)
        users = load_users()
        users[username]['uploads'] = users[username].get('uploads', 0) + 1
        save_json('users.json', users)

    return "Upload concluido: %s/s/%s" % (DOMAIN, short_id)


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
        return abort(404, "URL nao encontrada")

    data = short_urls[actual_id]
    filepath = os.path.join(UPLOAD_FOLDER, data['filename'])
    if not os.path.exists(filepath):
        return abort(404, "Arquivo nao encontrado")

    short_urls[actual_id]['views'] = data.get('views', 0) + 1
    save_json('short_urls.json', short_urls)

    if suffix == 'raw':
        return send_from_directory(UPLOAD_FOLDER, data['filename'])
    if suffix == 'info':
        return _build_info_page(data, actual_id)
    return _build_embed_page(data, actual_id, filepath)


def _build_info_page(data, actual_id):
    upload_date = datetime.fromisoformat(data['upload_time']).strftime('%d/%m/%Y as %H:%M')
    file_size = "%.2f MB" % (data.get('file_size', 0) / 1024 / 1024)
    is_video = data['filename'].lower().endswith(VIDEO_EXTENSIONS)
    embed_color = data.get('embed_color', '#0070f3')
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
    )


def _build_embed_page(data, actual_id, filepath):
    width, height = get_media_dimensions(filepath)
    if width < 400 or height < 300:
        width, height = max(width, 400), max(height, 300)

    is_video = data['filename'].lower().endswith(VIDEO_EXTENSIONS)
    embed_color = data.get('embed_color', '#0070f3')
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
# Routes — Admin
# ---------------------------------------------------------------------------
@app.route('/admin')
def admin_panel():
    if not is_admin():
        return abort(403, "Acesso negado")

    users = load_users()
    short_urls = load_json('short_urls.json')

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

    top_users_data = [
        {'username': u, 'uploads': d['uploads'], 'size_mb': d['size'] // 1024 // 1024}
        for u, d in top_users
    ]

    return render_template(
        'admin.html',
        users=users,
        total_files=len(short_urls),
        total_users=len(users),
        total_size_mb=total_size // 1024 // 1024,
        total_views=total_views,
        top_users=top_users_data,
    )


@app.route('/admin/create_user', methods=['GET', 'POST'])
def create_user():
    if not is_admin():
        return abort(403, "Acesso negado")

    if request.method == 'POST':
        new_username = sanitize_text(request.form.get('username', '').strip())
        new_password = request.form.get('password', '').strip()

        if not new_username or not new_password:
            return render_template('message.html', type='error',
                                   message="Usuario e senha obrigatorios.",
                                   back_url='/admin/create_user', back_text='Tentar novamente')
        if len(new_password) < 6:
            return render_template('message.html', type='error',
                                   message="Senha deve ter pelo menos 6 caracteres.",
                                   back_url='/admin/create_user', back_text='Tentar novamente')

        users = load_users()
        if new_username in users:
            return render_template('message.html', type='error',
                                   message="Usuario ja existe.",
                                   back_url='/admin/create_user', back_text='Tentar novamente')

        permissions = {
            'change_password': 'change_password' in request.form,
            'upload_videos': 'upload_videos' in request.form,
            'custom_urls': 'custom_urls' in request.form,
            'is_admin': 'is_admin' in request.form,
            'choose_embed_color': 'choose_embed_color' in request.form,
            'permanent_files': 'permanent_files' in request.form,
            'file_lifetime': int(request.form.get('file_lifetime', 0) or 0),
        }
        users[new_username] = {
            'password_hash': hash_password(new_password),
            'created': datetime.now().isoformat(),
            'uploads': 0,
            'permissions': permissions,
        }
        save_json('users.json', users)

        return render_template('message.html', type='success',
                               message="Usuario '%s' criado com sucesso." % new_username,
                               back_url='/admin', back_text='Voltar ao admin')

    return render_template('create_user.html')


@app.route('/admin/delete_user/<username>')
def delete_user(username):
    if not is_admin():
        return abort(403, "Acesso negado")
    users = load_users()
    if username in users and username != session.get('username'):
        del users[username]
        save_json('users.json', users)
    return redirect('/admin')


@app.route('/admin/cleanup')
def manual_cleanup():
    if not is_admin():
        return abort(403, "Acesso negado")
    cleanup_anonymous_files()
    return redirect('/admin')


# ---------------------------------------------------------------------------
# Routes — Tools
# ---------------------------------------------------------------------------
@app.route('/tools')
def tools():
    return render_template('tools.html')


@app.route('/tools/shortener', methods=['GET', 'POST'])
def url_shortener():
    if request.method == 'POST':
        original_url = request.form.get('url', '').strip()
        custom_alias = sanitize_text(request.form.get('custom_alias', '').strip())

        if not original_url:
            return jsonify({'error': 'URL e obrigatoria'})
        if not original_url.startswith(('http://', 'https://')):
            original_url = 'https://' + original_url

        shortened_links = load_json('shortened_links.json')

        if custom_alias:
            if custom_alias in shortened_links:
                return jsonify({'error': 'Alias ja existe'})
            short_id = custom_alias
        else:
            short_id = secrets.token_urlsafe(6)
            while short_id in shortened_links:
                short_id = secrets.token_urlsafe(6)

        shortened_links[short_id] = {
            'url': original_url,
            'created': datetime.now().isoformat(),
            'clicks': 0,
        }
        save_json('shortened_links.json', shortened_links)
        return jsonify({'success': True, 'short_url': "%s/l/%s" % (DOMAIN, short_id)})

    return render_template('shortener.html')


@app.route('/l/<short_id>')
def redirect_short_url(short_id):
    shortened_links = load_json('shortened_links.json')
    if short_id not in shortened_links:
        return abort(404, "Link nao encontrado")
    shortened_links[short_id]['clicks'] += 1
    save_json('shortened_links.json', shortened_links)
    return redirect(shortened_links[short_id]['url'])


@app.route('/tools/pastebin', methods=['GET', 'POST'])
def pastebin():
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        title = sanitize_text(request.form.get('title', 'Paste sem titulo'))
        syntax = request.form.get('syntax', 'text')
        try:
            expiry = int(request.form.get('expiry', 0) or 0)
        except (ValueError, TypeError):
            expiry = 0

        if not content:
            return jsonify({'error': 'Conteudo e obrigatorio'})
        if len(content.encode('utf-8')) > 30 * 1024 * 1024:
            return jsonify({'error': 'Conteudo muito grande (maximo 30MB)'})

        paste_id = secrets.token_urlsafe(10)
        paste_file = os.path.join(TOOLS_FOLDER, '%s.txt' % paste_id)
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
        }
        save_json('pastes.json', pastes)
        return jsonify({'success': True, 'paste_url': "%s/p/%s" % (DOMAIN, paste_id)})

    return render_template('pastebin.html')


@app.route('/p/<paste_id>')
def view_paste(paste_id):
    pastes = load_json('pastes.json')
    if paste_id not in pastes:
        return abort(404, "Paste nao encontrado")

    paste_data = pastes[paste_id]

    if paste_data.get('expires'):
        expire_time = datetime.fromisoformat(paste_data['expires'])
        if datetime.now() > expire_time:
            paste_file = os.path.join(TOOLS_FOLDER, '%s.txt' % paste_id)
            if os.path.exists(paste_file):
                os.remove(paste_file)
            del pastes[paste_id]
            save_json('pastes.json', pastes)
            return abort(404, "Paste expirado")

    pastes[paste_id]['views'] = paste_data.get('views', 0) + 1
    save_json('pastes.json', pastes)

    paste_file = os.path.join(TOOLS_FOLDER, '%s.txt' % paste_id)
    try:
        with open(paste_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return abort(404, "Arquivo nao encontrado")

    created_date = datetime.fromisoformat(paste_data['created']).strftime('%d/%m/%Y as %H:%M')
    expires_text = (
        "Nunca" if not paste_data.get('expires')
        else datetime.fromisoformat(paste_data['expires']).strftime('%d/%m/%Y as %H:%M')
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
        return abort(404, "Paste nao encontrado")
    paste_file = os.path.join(TOOLS_FOLDER, '%s.txt' % paste_id)
    try:
        with open(paste_file, 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except FileNotFoundError:
        return abort(404, "Arquivo nao encontrado")


# ---------------------------------------------------------------------------
# Routes — Deploy
# ---------------------------------------------------------------------------
DEPLOY_TOKEN = os.environ.get("DEPLOY_TOKEN", "hashhost-deploy-2024")

@app.route('/deploy', methods=['POST'])
def deploy_webhook():
    token = request.headers.get('X-Deploy-Token') or request.args.get('token')
    if token != DEPLOY_TOKEN:
        return abort(403, "Token invalido")
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
