import os, secrets, json, io, filetype, time, hashlib, threading, subprocess
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Flask, request, send_from_directory, abort, session, render_template_string, redirect, url_for, jsonify
from PIL import Image
import bleach
import bcrypt

app = Flask(__name__)

def auto_update():
    try:
        home = os.path.expanduser('~')
        repo = os.path.join(home, 'hashost')
        if os.path.isdir(os.path.join(repo, '.git')):
            subprocess.run(['git', '-C', repo, 'pull', 'origin', 'master'],
                          capture_output=True, timeout=15)
    except:
        pass

auto_update()
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
app.config.update({'UPLOAD_FOLDER': UPLOAD_FOLDER, 'MAX_CONTENT_LENGTH': 300*1024*1024})

DOMAIN = os.environ.get("DOMAIN", "https://hashost.pythonanywhere.com")
RATE_LIMIT_SECONDS = 5
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'video/mp4', 'video/webm', 'audio/mpeg', 'video/mov', 'audio/ogg'}
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.webm', '.mp3', '.mov', '.ogg'}
DANGEROUS_EXTENSIONS = {'.exe', '.bat', '.cmd', '.com', '.scr', '.pif', '.vbs', '.js', '.jar', '.php', '.asp', '.jsp', '.sh', '.py', '.pl', '.rb', '.html', '.htm', '.svg'}

def load_json(file, default=None):
    if default is None:
        default = {}
    try:
        with open(file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def hash_password_sha256(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

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
        users = {"admin": {
            "password_hash": hash_password("admin123"),
            "created": datetime.now().isoformat(),
            "uploads": 0,
            "permissions": {
                "change_password": True, "upload_videos": True, "custom_urls": True,
                "is_admin": True, "choose_embed_color": True, "permanent_files": True, "file_lifetime": 0
            }
        }}
        save_json('users.json', users)
    return users

def sanitize_text(text):
    return bleach.clean(str(text or ""), tags=[], strip=True).replace('<','').replace('>','').replace('"','').replace("'",'').replace('&','')[:200]

def check_rate_limit(username):
    rate_limits = load_json('rate_limits.json')
    if username in rate_limits and time.time() - rate_limits[username]['last_upload'] < RATE_LIMIT_SECONDS:
        return False, "Aguarde %d segundos" % int(RATE_LIMIT_SECONDS - (time.time() - rate_limits[username]['last_upload']))
    return True, "OK"

def update_rate_limit(username):
    rate_limits = load_json('rate_limits.json')
    rate_limits[username] = {'last_upload': time.time(), 'uploads_count': rate_limits.get(username, {}).get('uploads_count', 0) + 1}
    save_json('rate_limits.json', rate_limits)

def is_safe_file(file_content, filename, allow_video=False):
    ext = os.path.splitext(filename)[1].lower()
    if ext in DANGEROUS_EXTENSIONS:
        return False, "Tipo de arquivo perigoso"
    video_exts = {'.mp4', '.webm', '.avi', '.mov'}
    if ext in video_exts and not allow_video:
        return False, "Upload de videos nao autorizado"
    if ext not in ALLOWED_EXTENSIONS:
        return False, "Extensao nao permitida: %s" % ext
    max_size = 100*1024*1024 if allow_video else 20*1024*1024
    if len(file_content) < 100:
        return False, "Arquivo muito pequeno"
    if len(file_content) > max_size:
        return False, "Arquivo muito grande (maximo %dMB)" % (max_size//1024//1024)
    try:
        kind = filetype.guess(file_content)
        mime_type = kind.mime if kind else None
        if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
            return False, "MIME nao permitido: %s" % mime_type
        if ext not in video_exts:
            img = Image.open(io.BytesIO(file_content))
            img.verify()
    except Exception as e:
        return False, "Arquivo invalido: %s" % str(e)
    for sus in [b'<script', b'javascript:', b'vbscript:', b'onload=', b'onerror=']:
        if sus in file_content.lower():
            return False, "Conteudo suspeito"
    return True, "OK"

def get_media_dimensions(filepath):
    try:
        if filepath.lower().endswith(('.mp4', '.webm', '.avi', '.mov')):
            return (1200, 675)
        with Image.open(filepath) as img:
            return img.size
    except:
        return (1200, 630)

def cleanup_anonymous_files():
    try:
        short_urls = load_json('short_urls.json')
        current_time = datetime.now()
        to_remove = []
        for short_id, data in short_urls.items():
            if data.get('anonymous', False):
                upload_time = datetime.fromisoformat(data['upload_time'])
                if (current_time - upload_time).total_seconds() > 1200:
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

# ============================================================
# CSS
# ============================================================
CSS = """@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#000;--surface:#111;--surface2:#1a1a1a;--border:#222;--border2:#333;--text:#ededed;--text2:#888;--accent:#0070f3;--danger:#e00;--success:#0a0}
body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;min-height:100vh;line-height:1.5}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.container{max-width:960px;margin:0 auto;padding:24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:16px}
h1{font-size:24px;font-weight:600;letter-spacing:-0.02em}
h2{font-size:18px;font-weight:600}
.form-group{margin-bottom:20px}
.form-group label{display:block;margin-bottom:6px;color:var(--text2);font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em}
input[type="text"],input[type="password"],input[type="url"],input[type="email"],input[type="number"],input[type="color"],textarea,select{width:100%;padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:15px;font-family:inherit;transition:border-color .15s}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent)}
textarea{resize:vertical;font-family:'JetBrains Mono',monospace}
select option{background:var(--surface);color:var(--text)}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:500;border:none;cursor:pointer;transition:background .15s,transform .1s;text-decoration:none;gap:8px}
.btn:hover{transform:translateY(-1px);text-decoration:none}
.btn:active{transform:translateY(0)}
.btn-primary{background:var(--accent);color:#fff}.btn-primary:hover{background:#005fcc}
.btn-danger{background:var(--danger);color:#fff}.btn-danger:hover{background:#c00}
.btn-secondary{background:var(--surface2);color:var(--text);border:1px solid var(--border)}.btn-secondary:hover{background:var(--border)}
.btn-ghost{background:transparent;color:var(--text2);padding:8px 12px}.btn-ghost:hover{color:var(--text);background:var(--surface2)}
.btn-sm{padding:6px 12px;font-size:12px}
.error{color:var(--danger);background:rgba(224,0,0,0.08);border:1px solid rgba(224,0,0,0.2);padding:12px;border-radius:8px;font-size:14px;margin-bottom:16px}
.success{color:var(--success);background:rgba(0,170,0,0.08);border:1px solid rgba(0,170,0,0.2);padding:12px;border-radius:8px;font-size:14px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.stat{font-size:32px;font-weight:700;letter-spacing:-0.03em}
.stat-label{font-size:13px;color:var(--text2);margin-top:4px}
.badge{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600;background:var(--surface2);color:var(--text2);border:1px solid var(--border)}
.table{width:100%;border-collapse:collapse}
.table th,.table td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);font-size:14px}
.table th{color:var(--text2);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:0.05em}
.header{display:flex;justify-content:space-between;align-items:center;padding:16px 0;border-bottom:1px solid var(--border);margin-bottom:24px;flex-wrap:wrap;gap:12px}
.logo{font-size:18px;font-weight:700;letter-spacing:-0.03em;color:var(--text)}.logo span{color:var(--accent)}
.nav{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
@media(max-width:640px){.container{padding:16px}.grid{grid-template-columns:1fr}.header{flex-direction:column;align-items:flex-start}}
"""

# ============================================================
# LOGIN TEMPLATE
# ============================================================
LOGIN_TEMPLATE = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>""" + CSS + """</style></head><body><div style="display:flex;justify-content:center;align-items:center;min-height:100vh;padding:24px"><div style="width:100%;max-width:380px"><div style="text-align:center;margin-bottom:40px"><div style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:12px;background:var(--accent);color:#fff;font-size:22px;font-weight:700;margin-bottom:16px">H</div><h1 style="font-size:28px">HashHost</h1><p style="color:var(--text2);font-size:14px;margin-top:4px">Armazenamento e compartilhamento de arquivos</p></div>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><div class="form-group"><label>Usuario</label><input type="text" name="username" required autofocus placeholder="seu-usuario"></div><div class="form-group"><label>Senha</label><input type="password" name="password" required placeholder="sua-senha"></div><button type="submit" class="btn btn-primary" style="width:100%;margin-top:8px">Entrar</button></form></div></div></body></html>"""

# ============================================================
# DASHBOARD TEMPLATE
# ============================================================
_DASH_HEAD = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Painel</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>""" + CSS + """
.upload-zone{border:2px dashed var(--border2);border-radius:12px;padding:48px 24px;text-align:center;cursor:pointer;transition:border-color .15s,background .15s}
.upload-zone:hover,.upload-zone.dragover{border-color:var(--accent);background:rgba(0,112,243,0.04)}
.upload-zone p{color:var(--text2);font-size:14px;margin-top:8px}
.options{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}
@media(max-width:640px){.options{grid-template-columns:1fr}}
.result-box{margin-top:16px;padding:16px;background:var(--surface);border:1px solid var(--border);border-radius:8px;display:none}
.result-box a{word-break:break-all;font-family:monospace;font-size:14px}
</style></head><body><div class="container"><div class="header"><div class="logo">H<span>Host</span></div><div class="nav"><a href="/tools" class="btn btn-ghost">Tools</a>{IS_ADMIN_LINK}{PASS_LINK}<span class="badge">{USERNAME}</span><a href="/logout" class="btn btn-ghost">Sair</a></div></div><div class="card"><h2>Enviar arquivo</h2><p style="color:var(--text2);font-size:14px;margin-bottom:20px">Arraste ou selecione um arquivo para enviar.</p><form id="uploadForm" enctype="multipart/form-data"><div class="upload-zone" id="dropZone"><div style="font-size:36px;color:var(--text2)">+</div><p>Arraste o arquivo aqui ou clique para selecionar</p><input type="file" name="file" id="fileInput" style="display:none" accept="image/*,video/mp4,video/webm,audio/mpeg"></div><div id="previewBox" style="display:none;margin-top:16px;text-align:center"><img id="previewImg" src="" style="max-width:100%;max-height:300px;border-radius:8px;border:1px solid var(--border)" alt="Preview"></div><div class="options"><div class="form-group"><label>Titulo</label><input type="text" name="title" placeholder="Titulo opcional"></div><div class="form-group"><label>Descricao</label><input type="text" name="description" placeholder="Descricao opcional"></div>{CUSTOM_URL_FIELD}{COLOR_FIELD}</div><button type="submit" class="btn btn-primary" style="width:100%">Enviar</button></form><div class="result-box" id="resultBox"><p style="font-size:14px;color:var(--text2);margin-bottom:8px">Arquivo enviado:</p><a id="resultLink" href="#"></a><br><button class="btn btn-secondary btn-sm" style="margin-top:8px" onclick="navigator.clipboard.writeText(document.getElementById('resultLink').href)">Copiar link</button></div></div></div><script>const dz=document.getElementById('dropZone'),fi=document.getElementById('fileInput');dz.addEventListener('click',()=>fi.click());dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover')});dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');fi.files=e.dataTransfer.files;dz.querySelector('p').textContent=fi.files[0].name});fi.addEventListener('change',()=>{if(fi.files[0]){dz.querySelector('p').textContent=fi.files[0].name;const pb=document.getElementById('previewBox'),pi=document.getElementById('previewImg');if(fi.files[0].type.startsWith('image/')){const r=new FileReader();r.onload=e=>{pi.src=e.target.result;pb.style.display='block'};r.readAsDataURL(fi.files[0])}else{pb.style.display='none'}}});document.getElementById('uploadForm').addEventListener('submit',async e=>{e.preventDefault();const fd=new FormData(e.target);try{const r=await fetch('/upload',{method:'POST',body:fd});const t=await r.text();if(r.ok){document.getElementById('resultBox').style.display='block';document.getElementById('resultLink').href=t.replace('Upload concluido: ','');document.getElementById('resultLink').textContent=t.replace('Upload concluido: ','')}else{alert(t)}}catch(er){alert('Erro ao enviar')}});</script></body></html>"""

def build_dashboard(username, is_admin, can_change_password, can_custom_url, can_choose_embed_color):
    html = _DASH_HEAD
    html = html.replace("{USERNAME}", username)
    html = html.replace("{IS_ADMIN_LINK}", '<a href="/admin" class="btn btn-ghost">Admin</a>' if is_admin else "")
    html = html.replace("{PASS_LINK}", '<a href="/change_password" class="btn btn-ghost">Senha</a>' if can_change_password else "")
    html = html.replace("{CUSTOM_URL_FIELD}", '<div class="form-group"><label>URL personalizada</label><input type="text" name="custom_url" placeholder="meu-link"></div>' if can_custom_url else "")
    html = html.replace("{COLOR_FIELD}", '<div class="form-group"><label>Cor do embed</label><input type="color" name="embed_color" value="#0070f3"></div>' if can_choose_embed_color else "")
    return html

ANONYMOUS_TEMPLATE = build_dashboard("anonimo", "", "", "", "")

# ============================================================
# ROUTES
# ============================================================
@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    users = load_users()
    user = users.get(session['username'], {})
    perms = user.get('permissions', {})
    html = build_dashboard(
        session['username'],
        perms.get('is_admin', False),
        perms.get('change_password', False),
        perms.get('custom_urls', False),
        perms.get('choose_embed_color', False)
    )
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/anonymous')
def anonymous():
    return ANONYMOUS_TEMPLATE, 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = sanitize_text(request.form.get('username', '').strip())
        password = request.form.get('password', '')
        if not username or not password:
            return render_template_string(LOGIN_TEMPLATE, error="Usuario e senha obrigatorios")
        users = load_users()
        if username in users and check_password(password, users[username]['password_hash']):
            if not users[username]['password_hash'].startswith('$2'):
                upgrade_password(username, password)
            session['username'] = username
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=24)
            return redirect(url_for('index'))
        return render_template_string(LOGIN_TEMPLATE, error="Usuario ou senha incorretos")
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

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
    except:
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
    file_data = {
        'filename': random_name, 'original_filename': filename, 'title': title,
        'description': description, 'username': username,
        'upload_time': datetime.now().isoformat(), 'views': 0,
        'embed_color': embed_color, 'anonymous': not is_logged, 'file_size': len(file_content)
    }
    short_urls[short_id] = file_data
    save_json('short_urls.json', short_urls)
    if is_logged:
        update_rate_limit(username)
        users = load_users()
        users[username]['uploads'] = users[username].get('uploads', 0) + 1
        save_json('users.json', users)
    return "Upload concluido: %s/s/%s" % (DOMAIN, short_id)

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
    is_video = data['filename'].lower().endswith(('.mp4', '.webm', '.avi', '.mov'))
    embed_color = data.get('embed_color', '#0070f3')
    proxy_url = "%s/proxy/%s" % (DOMAIN, data['filename'])
    if is_video:
        media_html = '<video controls src="%s" style="max-width:300px;max-height:200px;border-radius:8px;border:1px solid var(--border)"></video>' % proxy_url
    else:
        media_html = '<img src="%s" alt="%s" style="max-width:300px;max-height:200px;border-radius:8px;border:1px solid var(--border)">' % (proxy_url, data['title'])
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>%s - Info</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:24px 0}@media(max-width:768px){.info-grid{grid-template-columns:1fr}}
.info-item{background:var(--surface2);padding:16px;border-radius:8px;border-left:3px solid %s}
.info-label{color:var(--text2);font-size:12px;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:4px}
.info-value{font-size:15px;font-weight:500}
.preview{text-align:center;margin:20px 0}
</style></head><body><div class="container"><div class="header"><a href="/" class="logo">H<span>Host</span></a><a href="/s/%s" class="btn btn-ghost">Voltar</a></div><div class="card"><h1 style="margin-bottom:16px">%s</h1><div style="text-align:center;margin:20px 0">%s</div><div class="info-grid"><div class="info-item"><div class="info-label">Arquivo</div><div class="info-value">%s</div></div><div class="info-item"><div class="info-label">Enviado por</div><div class="info-value">%s</div></div><div class="info-item"><div class="info-label">Data</div><div class="info-value">%s</div></div><div class="info-item"><div class="info-label">Tamanho</div><div class="info-value">%s</div></div><div class="info-item"><div class="info-label">Visualizacoes</div><div class="info-value">%s</div></div><div class="info-item"><div class="info-label">Tipo</div><div class="info-value">%s</div></div></div></div></div></body></html>""" % (
        data['title'], CSS, embed_color, actual_id, data['title'], media_html,
        data['original_filename'], data['username'], upload_date, file_size,
        data.get('views', 0), data['filename'].split('.')[-1].upper()
    )

def _build_embed_page(data, actual_id, filepath):
    width, height = get_media_dimensions(filepath)
    if width < 400 or height < 300:
        width, height = max(width, 400), max(height, 300)
    is_video = data['filename'].lower().endswith(('.mp4', '.webm', '.avi', '.mov'))
    embed_color = data.get('embed_color', '#0070f3')
    proxy_url = "%s/proxy/%s" % (DOMAIN, data['filename'])
    if is_video:
        media_html = '<video controls style="max-width:100%%;height:auto;border:1px solid #333;border-radius:8px" src="%s"></video>' % proxy_url
    else:
        media_html = '<img src="%s" alt="%s" style="max-width:100%%;height:auto;border:1px solid #333;border-radius:8px">' % (proxy_url, data['title'])
    info_link = "%s/s/%s/info" % (DOMAIN, actual_id)
    raw_link = "%s/s/%s/raw" % (DOMAIN, actual_id)
    html = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><meta property="og:type" content="article"><meta property="og:title" content="%s"><meta property="og:description" content="%s"><meta property="og:image" content="%s"><meta property="og:image:width" content="%d"><meta property="og:image:height" content="%d"><meta name="theme-color" content="%s"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="%s"><title>%s</title></head><body style="margin:0;padding:20px;background:#000;color:#ededed;text-align:center;font-family:'JetBrains Mono',monospace"><h1 style="font-size:24px;font-weight:600;margin-bottom:16px;color:#ededed">%s</h1><p style="color:#888;margin:16px 0;font-size:14px">%s</p>%s<div style="margin-top:24px"><a href="%s" style="background:#1a1a1a;color:#ededed;padding:10px 20px;border-radius:8px;text-decoration:none;margin:0 8px;font-size:14px;border:1px solid #333">Info</a><a href="%s" style="background:#0070f3;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin:0 8px;font-size:14px">Link direto</a></div></body></html>""" % (
        data['title'], data['description'], proxy_url, width, height, embed_color,
        proxy_url, data['title'], data['title'], data['description'], media_html,
        info_link, raw_link
    )
    response = app.response_class(html, 200, mimetype='text/html; charset=utf-8')
    response.headers.update({'Cache-Control': 'no-cache, no-store, must-revalidate'})
    return response

@app.route('/proxy/<filename>')
def proxy_image(filename):
    filename = secure_filename(filename)
    if not os.path.exists(os.path.join(UPLOAD_FOLDER, filename)):
        return abort(404)
    response = send_from_directory(UPLOAD_FOLDER, filename)
    response.headers.update({'Cache-Control': 'public, max-age=3600', 'Access-Control-Allow-Origin': '*'})
    return response

@app.route('/admin')
def admin_panel():
    if 'username' not in session or not load_users().get(session['username'], {}).get('permissions', {}).get('is_admin', False):
        return abort(403, "Acesso negado")
    users = load_users()
    short_urls = load_json('short_urls.json')
    total_size = 0
    for data in short_urls.values():
        fp = os.path.join(UPLOAD_FOLDER, data['filename'])
        if os.path.exists(fp):
            total_size += os.path.getsize(fp)
    user_stats = {}
    for data in short_urls.values():
        u = data['username']
        if u not in user_stats:
            user_stats[u] = {'uploads': 0, 'size': 0}
        user_stats[u]['uploads'] += 1
        user_stats[u]['size'] += data.get('file_size', 0)
    top_users = sorted(user_stats.items(), key=lambda x: x[1]['uploads'], reverse=True)[:10]
    total_views = sum(d.get('views', 0) for d in short_urls.values())
    user_rows = ""
    for u, d in users.items():
        user_rows += '<div class="user-item"><div><strong>%s</strong> <span class="badge">%d envios</span></div><div class="user-actions"><a href="/admin/delete_user/%s" class="btn btn-danger btn-sm" onclick="return confirm(\'Remover %s?\')">Remover</a></div></div>' % (u, d.get('uploads', 0), u, u)
    top_rows = ""
    for u, d in top_users:
        top_rows += '<tr><td>%s</td><td>%d</td><td>%d MB</td></tr>' % (u, d['uploads'], d['size'] // 1024 // 1024)
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Admin</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s
.stat-card{text-align:center;padding:24px}
.user-item{display:flex;justify-content:space-between;align-items:center;padding:12px;background:var(--surface2);border-radius:8px;margin-bottom:8px}
.user-actions{display:flex;gap:8px}
</style></head><body><div class="container"><div class="header"><a href="/" class="logo">H<span>Host</span></a><div class="nav"><a href="/admin/creat" class="btn btn-primary btn-sm">Novo usuario</a><a href="/admin/cleanup" class="btn btn-secondary btn-sm">Limpar anonimos</a><a href="/" class="btn btn-ghost btn-sm">Voltar</a></div></div><h1 style="margin-bottom:24px">Painel administrativo</h1><div class="grid"><div class="card stat-card"><div class="stat">%d</div><div class="stat-label">Arquivos</div></div><div class="card stat-card"><div class="stat">%d</div><div class="stat-label">Usuarios</div></div><div class="card stat-card"><div class="stat">%d MB</div><div class="stat-label">Espaco usado</div></div><div class="card stat-card"><div class="stat">%d</div><div class="stat-label">Visualizacoes</div></div></div><div class="card" style="margin-top:16px"><h2 style="margin-bottom:16px">Usuarios</h2>%s</div><div class="card" style="margin-top:16px"><h2 style="margin-bottom:16px">Top envios</h2><table class="table"><thead><tr><th>Usuario</th><th>Envios</th><th>Tamanho</th></tr></thead><tbody>%s</tbody></table></div></div></body></html>""" % (
        CSS, len(short_urls), len(users), total_size // 1024 // 1024, total_views, user_rows, top_rows
    )

@app.route('/admin/create_user', methods=['GET', 'POST'])
def create_user():
    if 'username' not in session or not load_users().get(session['username'], {}).get('permissions', {}).get('is_admin', False):
        return abort(403, "Acesso negado")
    if request.method == 'POST':
        new_username = sanitize_text(request.form.get('username', '').strip())
        new_password = request.form.get('password', '').strip()
        if not new_username or not new_password:
            return "Usuario e senha obrigatorios"
        if len(new_password) < 6:
            return "Senha deve ter pelo menos 6 caracteres"
        users = load_users()
        if new_username in users:
            return "Usuario ja existe"
        permissions = {
            'change_password': 'change_password' in request.form,
            'upload_videos': 'upload_videos' in request.form,
            'custom_urls': 'custom_urls' in request.form,
            'is_admin': 'is_admin' in request.form,
            'choose_embed_color': 'choose_embed_color' in request.form,
            'permanent_files': 'permanent_files' in request.form,
            'file_lifetime': int(request.form.get('file_lifetime', 0) or 0)
        }
        users[new_username] = {
            'password_hash': hash_password(new_password),
            'created': datetime.now().isoformat(),
            'uploads': 0,
            'permissions': permissions
        }
        save_json('users.json', users)
        return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost</title><style>%s</style></head><body><div class="container" style="text-align:center;padding-top:80px"><div class="success">Usuario '%s' criado com sucesso.</div><a href="/admin" class="btn btn-primary" style="margin-top:16px">Voltar ao admin</a></div></body></html>""" % (CSS, new_username)
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Novo usuario</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s</style></head><body><div class="container" style="max-width:480px"><div class="header"><a href="/admin" class="logo">H<span>Host</span></a><a href="/admin" class="btn btn-ghost">Voltar</a></div><div class="card"><h2 style="margin-bottom:24px">Novo usuario</h2><form method="POST"><div class="form-group"><label>Nome de usuario</label><input type="text" name="username" required maxlength="50" placeholder="nome-do-usuario"></div><div class="form-group"><label>Senha</label><input type="password" name="password" required minlength="6" placeholder="minimo 6 caracteres"></div><div class="form-group"><label>Vida util dos arquivos (horas, 0 = permanente)</label><input type="number" name="file_lifetime" value="0" min="0"></div><h2 style="margin:24px 0 16px;font-size:16px">Permissoes</h2><div class="grid" style="grid-template-columns:1fr 1fr"><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" name="change_password" checked> Alterar senha</label><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" name="upload_videos" checked> Enviar videos</label><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" name="custom_urls" checked> URLs customizadas</label><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" name="is_admin"> Admin</label><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" name="choose_embed_color" checked> Cor do embed</label><label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer"><input type="checkbox" name="permanent_files" checked> Arquivos permanentes</label></div><button type="submit" class="btn btn-primary" style="width:100%%;margin-top:24px">Criar usuario</button></form></div></div></body></html>""" % CSS

@app.route('/tools')
def tools():
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Tools</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s
.tool-card{padding:32px;text-align:center;transition:border-color .15s;cursor:pointer}
.tool-card:hover{border-color:var(--accent)}
.tool-icon{font-size:40px;margin-bottom:16px;color:var(--text2)}
.tool-title{font-size:18px;font-weight:600;margin-bottom:8px}
.tool-desc{color:var(--text2);font-size:14px;line-height:1.6}
</style></head><body><div class="container"><div class="header"><a href="/" class="logo">H<span>Host</span></a><a href="/" class="btn btn-ghost">Voltar</a></div><h1 style="margin-bottom:8px">Tools</h1><p style="color:var(--text2);margin-bottom:24px;font-size:14px">Ferramentas para uso diario.</p><div class="grid"><a href="/tools/shortener" class="card tool-card" style="text-decoration:none;color:inherit"><div class="tool-icon">/</div><div class="tool-title">Encurtador de links</div><div class="tool-desc">Encurte URLs longas em links curtos e rastreaveis.</div></a><a href="/tools/pastebin" class="card tool-card" style="text-decoration:none;color:inherit"><div class="tool-icon">{ }</div><div class="tool-title">Pastebin</div><div class="tool-desc">Cole e compartilhe trechos de codigo ou texto.</div></a></div></div></body></html>""" % CSS

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
        shortened_links[short_id] = {'url': original_url, 'created': datetime.now().isoformat(), 'clicks': 0}
        save_json('shortened_links.json', shortened_links)
        return jsonify({'success': True, 'short_url': "%s/l/%s" % (DOMAIN, short_id)})
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Encurtador</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s
.result{margin-top:16px;padding:16px;background:var(--surface);border:1px solid var(--border);border-radius:8px;display:none}
.link-box{display:flex;gap:8px;align-items:center;margin-top:8px}
.link-box input{flex:1;font-family:monospace;font-size:14px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:8px}
</style></head><body><div class="container" style="max-width:560px"><div class="header"><a href="/tools" class="logo">H<span>Host</span></a><a href="/tools" class="btn btn-ghost">Voltar</a></div><div class="card"><h2 style="margin-bottom:20px">Encurtador de links</h2><form id="shortenerForm"><div class="form-group"><label>URL para encurtar</label><input type="url" name="url" placeholder="https://exemplo.com/url-muito-longa" required></div><div class="form-group"><label>Alias (opcional)</label><input type="text" name="custom_alias" placeholder="meu-link"></div><button type="submit" class="btn btn-primary" style="width:100%%">Encurtar</button></form><div class="result" id="result"><p style="font-size:13px;color:var(--text2)">Link encurtado:</p><div class="link-box"><input type="text" id="shortUrl" readonly><button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('shortUrl').value)">Copiar</button></div></div></div></div><script>document.getElementById('shortenerForm').addEventListener('submit',async e=>{e.preventDefault();const fd=new URLSearchParams(new FormData(e.target));const r=await fetch('/tools/shortener',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:fd});const d=await r.json();if(d.short_url){document.getElementById('result').style.display='block';document.getElementById('shortUrl').value=d.short_url}else{alert(d.error)}});</script></body></html>""" % CSS

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
        pastes[paste_id] = {'title': title, 'syntax': syntax, 'created': datetime.now().isoformat(), 'expires': expire_time, 'views': 0, 'size': len(content.encode('utf-8'))}
        save_json('pastes.json', pastes)
        return jsonify({'success': True, 'paste_url': "%s/p/%s" % (DOMAIN, paste_id)})
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Pastebin</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s
.paste-textarea{height:400px;font-family:'JetBrains Mono',monospace;font-size:14px;line-height:1.5}
.result{margin-top:16px;padding:16px;background:var(--surface);border:1px solid var(--border);border-radius:8px;display:none}
.link-box{display:flex;gap:8px;align-items:center;margin-top:8px}
.link-box input{flex:1;font-family:monospace;font-size:14px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:8px}
</style></head><body><div class="container" style="max-width:720px"><div class="header"><a href="/tools" class="logo">H<span>Host</span></a><a href="/tools" class="btn btn-ghost">Voltar</a></div><div class="card"><h2 style="margin-bottom:20px">Pastebin</h2><form id="pasteForm"><div class="form-group"><label>Conteudo</label><textarea name="content" class="paste-textarea" placeholder="Cole o codigo ou texto aqui..." required></textarea></div><div class="grid"><div class="form-group"><label>Titulo</label><input type="text" name="title" placeholder="Titulo opcional"></div><div class="form-group"><label>Linguagem</label><select name="syntax"><option value="text">Texto</option><option value="python">Python</option><option value="javascript">JavaScript</option><option value="html">HTML</option><option value="css">CSS</option><option value="sql">SQL</option><option value="bash">Bash</option><option value="json">JSON</option><option value="xml">XML</option></select></div></div><div class="form-group"><label>Expirar em (horas, 0 = nunca)</label><input type="number" name="expiry" value="0" min="0"></div><button type="submit" class="btn btn-primary" style="width:100%%">Criar paste</button></form><div class="result" id="result"><p style="font-size:13px;color:var(--text2)">Paste criado:</p><div class="link-box"><input type="text" id="pasteUrl" readonly><button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('pasteUrl').value)">Copiar</button></div></div></div></div><script>document.getElementById('pasteForm').addEventListener('submit',async e=>{e.preventDefault();const fd=new URLSearchParams(new FormData(e.target));const r=await fetch('/tools/pastebin',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:fd});const d=await r.json();if(d.paste_url){document.getElementById('result').style.display='block';document.getElementById('pasteUrl').value=d.paste_url}else{alert(d.error)}});</script></body></html>""" % CSS

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
    except:
        return abort(404, "Arquivo nao encontrado")
    created_date = datetime.fromisoformat(paste_data['created']).strftime('%d/%m/%Y as %H:%M')
    expires_text = "Nunca" if not paste_data.get('expires') else datetime.fromisoformat(paste_data['expires']).strftime('%d/%m/%Y as %H:%M')
    safe_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>%s - HashHost</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s
.content-box{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:20px;margin:20px 0;overflow-x:auto}
.content{font-family:'JetBrains Mono',monospace;white-space:pre-wrap;color:var(--text);line-height:1.6;font-size:14px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}
@media(max-width:640px){.stats{grid-template-columns:1fr}}
.stat-item{background:var(--surface2);padding:12px;border-radius:8px;text-align:center}
.stat-label{color:var(--text2);font-size:11px;text-transform:uppercase;letter-spacing:0.05em}
.stat-value{font-size:16px;font-weight:600;margin-top:4px}
</style></head><body><div class="container"><div class="header"><a href="/tools" class="logo">H<span>Host</span></a><div class="nav"><a href="/p/%s/raw" class="btn btn-secondary btn-sm">Raw</a><a href="/tools/pastebin" class="btn btn-ghost btn-sm">Novo paste</a></div></div><div class="card"><h1 style="margin-bottom:8px">%s</h1><p style="color:var(--text2);font-size:13px">Criado em %s / %s</p><div class="stats"><div class="stat-item"><div class="stat-label">Visualizacoes</div><div class="stat-value">%s</div></div><div class="stat-item"><div class="stat-label">Tamanho</div><div class="stat-value">%d KB</div></div><div class="stat-item"><div class="stat-label">Expira em</div><div class="stat-value">%s</div></div></div><div class="content-box"><div class="content">%s</div></div><div style="text-align:center;margin-top:16px"><a href="/p/%s/raw" class="btn btn-primary">Ver em texto puro</a></div></div></div></body></html>""" % (
        paste_data['title'], CSS, paste_id, paste_data['title'], created_date,
        paste_data['syntax'].title(), paste_data.get('views', 0),
        paste_data.get('size', 0) // 1024, expires_text, safe_content, paste_id
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
    except:
        return abort(404, "Arquivo nao encontrado")

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
        err_html = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost</title><style>%s</style></head><body><div class="container" style="max-width:400px;padding-top:80px;text-align:center"><div class="error">%%s</div><a href="/change_password" class="btn btn-primary" style="margin-top:16px">Tentar novamente</a></div></body></html>""" % CSS
        ok_html = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost</title><style>%s</style></head><body><div class="container" style="max-width:400px;padding-top:80px;text-align:center"><div class="success">%%s</div><a href="/" class="btn btn-primary" style="margin-top:16px">Voltar ao painel</a></div></body></html>""" % CSS
        if not current_password or not new_password or not confirm_password:
            return err_html % "Todos os campos sao obrigatorios."
        if not check_password(current_password, user['password_hash']):
            return err_html % "Senha atual incorreta."
        if new_password != confirm_password:
            return err_html % "Senhas nao coincidem."
        if len(new_password) < 6:
            return err_html % "Nova senha deve ter pelo menos 6 caracteres."
        users[session['username']]['password_hash'] = hash_password(new_password)
        save_json('users.json', users)
        return ok_html % "Senha alterada com sucesso."
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>HashHost - Alterar senha</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>%s</style></head><body><div class="container" style="max-width:420px"><div class="header"><a href="/" class="logo">H<span>Host</span></a><a href="/" class="btn btn-ghost">Voltar</a></div><div class="card"><h2 style="margin-bottom:24px">Alterar senha</h2><form method="POST"><div class="form-group"><label>Senha atual</label><input type="password" name="current_password" required></div><div class="form-group"><label>Nova senha</label><input type="password" name="new_password" required minlength="6"></div><div class="form-group"><label>Confirmar nova senha</label><input type="password" name="confirm_password" required minlength="6"></div><button type="submit" class="btn btn-primary" style="width:100%%">Alterar senha</button></form></div></div></body></html>""" % CSS

@app.route('/admin/cleanup')
def manual_cleanup():
    if 'username' not in session or not load_users().get(session['username'], {}).get('permissions', {}).get('is_admin', False):
        return abort(403, "Acesso negado")
    cleanup_anonymous_files()
    return redirect('/admin?msg=Limpeza realizada com sucesso!')

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

if __name__ == '__main__':
    app.run(debug=False)
