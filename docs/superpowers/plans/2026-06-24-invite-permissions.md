# Invite Permissions System - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow admins and team members to create invites with custom permissions (1-50 uses) and a permission picker that respects the creator's own permission level.

**Architecture:** Add a permission picker UI to both admin and account invite forms. Store selected permissions in the invite's `permissions` field. Admins can grant any permission; team members can only grant permissions they themselves possess. Signup applies the invite's permissions to the new user.

**Tech Stack:** Flask, Jinja2, vanilla JS, JSON storage

## Global Constraints

- Dark theme, JetBrains Mono font, no emojis
- All communication in Portuguese with proper accents
- Permission hierarchy: is_admin > is_team > can_create_invites > individual perms
- Team members can only grant permissions they have
- Invite max_uses: 1-50 (integer), or -1 for unlimited
- Existing invites with `permissions: null` continue to work (fallback to MINIMAL_PERMISSIONS)

---

## File Map

| File | Responsibility |
|------|---------------|
| `app.py` | Invite generation logic, permission validation, signup permission assignment |
| `templates/admin.html` | Admin invite form with permission picker |
| `templates/account.html` | Account invite form with permission picker |

---

### Task 1: Permission Picker HTML Component

**Files:**
- Modify: `templates/admin.html` (lines 121-216, invite form section)
- Modify: `templates/account.html` (lines 116-175, invite section)

**Interfaces:**
- Consumes: `perms` (creator's permissions), `file_lifetime_options` (template variable)
- Produces: Form fields `perm_<name>` for each permission, `max_uses` integer input

- [ ] **Step 1: Add permission picker to admin invite form**

Replace the admin invite form (the `<form id="inviteForm">` block) with:

```html
<form id="inviteForm" style="display:flex;flex-direction:column;gap:12px">
  <div style="display:flex;gap:8px;align-items:center">
    <label style="color:var(--text2);font-size:12px;white-space:nowrap">Usos:</label>
    <input type="number" name="max_uses" value="1" min="1" max="50" style="width:70px;padding:6px 10px;font-size:13px;background:var(--surface2);color:var(--text1);border:1px solid var(--border);border-radius:6px">
    <span style="color:var(--text3);font-size:11px">ou -1 para ilimitado</span>
  </div>
  <div>
    <div style="color:var(--text2);font-size:12px;margin-bottom:8px">Permissões do convidado</div>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:6px">
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
        <input type="checkbox" name="perm_is_team" value="1"> Equipe
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
        <input type="checkbox" name="perm_can_create_invites" value="1"> Criar invites
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
        <input type="checkbox" name="perm_can_change_title" value="1" checked> Alterar título
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
        <input type="checkbox" name="perm_can_use_hashbin" value="1"> HashBin
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
        <input type="checkbox" name="perm_can_change_password" value="1" checked> Alterar senha
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
        <input type="checkbox" name="perm_can_choose_embed_color" value="1" checked> Cor do embed
      </label>
    </div>
    <div style="margin-top:8px">
      <label style="color:var(--text2);font-size:12px">Vida útil das mídias</label>
      <select name="perm_file_lifetime" multiple size="4" style="width:100%;height:auto;margin-top:4px;padding:6px;font-size:12px;background:var(--surface2);color:var(--text1);border:1px solid var(--border);border-radius:6px">
        {% for opt in file_lifetime_options %}
        <option value="{{ opt.value }}" {% if opt.value == '0' %}selected{% endif %}>{{ opt.label }}</option>
        {% endfor %}
      </select>
    </div>
  </div>
  <div>
    <button type="submit" class="btn btn-primary btn-sm">Gerar invite</button>
  </div>
</form>
```

- [ ] **Step 2: Add permission picker to account invite form**

Replace the account invite form with:

```html
{% if perms.can_create_invites %}
<div class="card reveal" style="margin-top:16px">
  <div class="section">
    <h2 class="section-title">Convites</h2>
    {% if perms.invite_count != 0 %}
    <form method="POST" id="accountInviteForm" style="display:flex;flex-direction:column;gap:12px">
      <input type="hidden" name="action" value="generate_invite">
      <div style="display:flex;gap:8px;align-items:center">
        <label style="color:var(--text2);font-size:12px;white-space:nowrap">Usos:</label>
        <input type="number" name="max_uses" value="1" min="1" max="50" style="width:70px;padding:6px 10px;font-size:13px;background:var(--surface2);color:var(--text1);border:1px solid var(--border);border-radius:6px">
        <span style="color:var(--text3);font-size:11px">ou -1 para ilimitado</span>
      </div>
      <div>
        <div style="color:var(--text2);font-size:12px;margin-bottom:8px">Permissões do convidado</div>
        <div class="grid" style="grid-template-columns:1fr 1fr;gap:6px">
          {% if perms.is_admin or perms.is_team %}
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
            <input type="checkbox" name="perm_is_team" value="1"> Equipe
          </label>
          {% endif %}
          {% if perms.is_admin or perms.can_create_invites %}
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
            <input type="checkbox" name="perm_can_create_invites" value="1"> Criar invites
          </label>
          {% endif %}
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
            <input type="checkbox" name="perm_can_change_title" value="1" checked> Alterar título
          </label>
          {% if perms.is_admin or perms.is_team %}
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
            <input type="checkbox" name="perm_can_use_hashbin" value="1"> HashBin
          </label>
          {% endif %}
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
            <input type="checkbox" name="perm_can_change_password" value="1" checked> Alterar senha
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;color:var(--text2)">
            <input type="checkbox" name="perm_can_choose_embed_color" value="1" checked> Cor do embed
          </label>
        </div>
        <div style="margin-top:8px">
          <label style="color:var(--text2);font-size:12px">Vida útil das mídias</label>
          <select name="perm_file_lifetime" multiple size="4" style="width:100%;height:auto;margin-top:4px;padding:6px;font-size:12px;background:var(--surface2);color:var(--text1);border:1px solid var(--border);border-radius:6px">
            {% for opt in file_lifetime_options %}
            <option value="{{ opt.value }}" {% if opt.value == '0' %}selected{% endif %}>{{ opt.label }}</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div>
        <button type="submit" class="btn btn-primary btn-sm">Gerar convite</button>
      </div>
    </form>
    {% else %}
    <p style="color:var(--text2);font-size:12px;margin-bottom:12px">Limite de invites atingido</p>
    {% endif %}

    {% if perms.invite_count != 0 %}
    <p style="color:var(--text2);font-size:12px;margin-top:8px">Restam {{ perms.invite_count }} convites</p>
    {% endif %}

    {# ... existing invite list rendering stays the same ... #}
  </div>
</div>
{% endif %}
```

- [ ] **Step 3: Update admin JS to send permission fields**

Replace the `<script>` block at the bottom of admin.html (the inviteForm handler) with:

```html
<script>
  document.getElementById('inviteForm').addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await fetch('/admin/generate_invite', { method: 'POST', body: fd });
      const data = await r.json();
      if (data.success) {
        location.reload();
      } else {
        alert(data.error || 'Erro ao gerar invite');
      }
    } catch (err) {
      alert('Erro ao gerar invite');
    }
  });
</script>
```

(This is the same JS — the FormData already captures all named fields including the new `perm_*` fields.)

- [ ] **Step 4: Verify template renders without errors**

Load the admin page and account page in browser. Confirm:
- Permission checkboxes appear in the invite form
- `max_uses` shows as number input (1-50)
- File lifetime select appears
- Existing invite list still renders correctly

- [ ] **Step 5: Commit**

```bash
git add templates/admin.html templates/account.html
git commit -m "feat: invite permission picker UI in admin and account"
```

---

### Task 2: Backend — Invite Generation with Permissions

**Files:**
- Modify: `app.py` — account route `generate_invite` action (lines 1155-1182)
- Modify: `app.py` — admin route `/admin/generate_invite` (lines 1496-1539)

**Interfaces:**
- Consumes: `request.form` with `perm_*` fields, `max_uses`, creator's `perms`
- Produces: `invites.json` entries with populated `permissions` dict

- [ ] **Step 1: Add permission extraction helper in app.py**

Add after the `generate_invite_code()` function (around line 388):

```python
ALL_PERMISSIONS = ['is_team', 'can_create_invites', 'can_change_title',
                   'can_use_hashbin', 'can_change_password', 'can_choose_embed_color']

def extract_invite_permissions(form, creator_perms):
    """Extract permissions from form, respecting creator's permission level."""
    perms = {}
    is_creator_admin = creator_perms.get('is_admin', False)

    for perm in ALL_PERMISSIONS:
        if perm in form and form.get('perm_' + perm) == '1':
            if is_creator_admin or creator_perms.get(perm, False):
                perms[perm] = True

    file_lifetime = form.getlist('perm_file_lifetime') or ['0']
    perms['file_lifetime'] = file_lifetime

    perms['is_admin'] = False
    perms['invite_count'] = 0
    perms['hashbin_lifetime'] = ['0']

    return perms
```

- [ ] **Step 2: Update account route generate_invite action**

Replace the `generate_invite` action block (lines 1155-1182) with:

```python
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
                    if max_uses < -1 or max_uses == 0:
                        max_uses = 1
                    if max_uses > 50:
                        max_uses = 50
                    invite_perms = extract_invite_permissions(request.form, perms)
                    invites[code] = {
                        'created_by': username,
                        'created_at': datetime.now().isoformat(),
                        'used': False,
                        'used_by': None,
                        'expires': None,
                        'permissions': invite_perms,
                        'max_uses': max_uses,
                        'use_count': 0,
                    }
                    save_json('invites.json', invites)
                    if invite_count > 0:
                        users[username]['permissions']['invite_count'] = max(0, invite_count - 1)
                        save_json('users.json', users)
                    success = "Convite criado"
```

- [ ] **Step 3: Update admin route /admin/generate_invite**

Replace the function body (lines 1496-1539) with:

```python
@app.route('/admin/generate_invite', methods=['POST'])
def generate_invite():
    if not is_admin_user():
        return jsonify({'error': 'Sem permissão'})

    users = load_users()
    admin_user = users.get(session['username'], {})
    admin_perms = admin_user.get('permissions', {})

    max_uses = int(request.form.get('max_uses', 1) or 1)
    if max_uses < -1 or max_uses == 0:
        max_uses = 1
    if max_uses > 50:
        max_uses = 50

    invite_perms = extract_invite_permissions(request.form, admin_perms)

    invites = load_json('invites.json')
    code = generate_invite_code()
    while code in invites:
        code = generate_invite_code()

    invites[code] = {
        'created_by': session['username'],
        'created_at': datetime.now().isoformat(),
        'used': False,
        'used_by': None,
        'expires': None,
        'permissions': invite_perms,
        'max_uses': max_uses,
        'use_count': 0,
    }

    save_json('invites.json', invites)
    return jsonify({'success': True, 'invites': [code]})
```

- [ ] **Step 4: Test invite generation**

1. Login as admin
2. Go to account → Convites
3. Set max_uses to 5, check "Equipe" + "Alterar título", select file lifetime
4. Click "Gerar convite"
5. Verify the invite appears in the list
6. Check `invites.json` — confirm `permissions` dict is populated (not null)

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: invite generation with custom permissions and max_uses 1-50"
```

---

### Task 3: Backend — Signup Applies Invite Permissions

**Files:**
- Modify: `app.py` — signup route (lines 498-579)

**Interfaces:**
- Consumes: `invites[code]['permissions']` dict
- Produces: New user with permissions from the invite

- [ ] **Step 1: Update signup route permission assignment**

The signup route already reads `invite_perms = invites[invite_code].get('permissions')` and falls back to `MINIMAL_PERMISSIONS`. The change needed is to ensure the new user's `is_admin` is always False (never granted via invite) and that `invite_count` is set based on `can_create_invites`:

Find this block in the signup route:

```python
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
```

Replace with:

```python
            invite_perms = invites[invite_code].get('permissions')
            if invite_perms:
                user_permissions = invite_perms.copy()
            else:
                user_permissions = MINIMAL_PERMISSIONS.copy()

            user_permissions['is_admin'] = False
            if user_permissions.get('can_create_invites', False) and 'invite_count' not in user_permissions:
                user_permissions['invite_count'] = 3
            if not user_permissions.get('can_create_invites', False):
                user_permissions['invite_count'] = 0

            users[username] = {
                'password_hash': hash_password(password),
                'created': datetime.now().isoformat(),
                'uploads': 0,
                'status': 'approved',
                'permissions': user_permissions,
                'profile': {},
            }
```

- [ ] **Step 2: Test signup flow**

1. Login as admin, create an invite with permissions: Equipe=True, can_change_title=True, can_create_invites=False
2. Open the invite URL `/iv/<code>` in incognito
3. Register a new user
4. Login as the new user
5. Verify: user can change title, cannot create invites, is not admin, is not team

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: signup applies invite permissions with admin safety check"
```

---

### Task 4: Display Permissions on Invite List

**Files:**
- Modify: `templates/admin.html` (invite list loop)
- Modify: `templates/account.html` (invite list loop)

**Interfaces:**
- Consumes: `invite.permissions` dict from invites.json
- Produces: Visual badge/label showing granted permissions

- [ ] **Step 1: Add permission badges to admin invite list**

Inside the `{% for code, invite in invites.items() %}` loop in admin.html, after the usage count line, add:

```html
              {% if invite.permissions %}
              <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">
                {% for perm, val in invite.permissions.items() %}
                  {% if val == true and perm != 'file_lifetime' %}
                  <span style="background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:1px 6px;font-size:10px;color:var(--text2)">{{ perm }}</span>
                  {% endif %}
                {% endfor %}
                {% if invite.permissions.file_lifetime is defined %}
                <span style="background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:1px 6px;font-size:10px;color:var(--text2)">lifetime: {{ invite.permissions.file_lifetime | join(', ') }}</span>
                {% endif %}
              </div>
              {% endif %}
```

- [ ] **Step 2: Add same permission badges to account invite list**

Same pattern in account.html invite loop.

- [ ] **Step 3: Commit**

```bash
git add templates/admin.html templates/account.html
git commit -m "feat: show permission badges on invite list items"
```

---

### Task 5: Migration for Existing Invites

**Files:**
- Modify: `app.py` — no migration needed for invites (null permissions fallback works)

**Verification:**
- Existing invites with `permissions: null` continue to grant `MINIMAL_PERMISSIONS` on signup
- No data migration required

- [ ] **Step 1: Verify backward compatibility**

Confirm that the signup route's `else: user_permissions = MINIMAL_PERMISSIONS.copy()` branch still works for old invites.

- [ ] **Step 2: Final commit if any cleanup needed**

---

### Task 6: End-to-End Test

- [ ] **Step 1: Test admin invite with custom permissions**

1. Login as admin
2. Create invite: max_uses=3, permissions=Equipe+can_change_title+can_change_password
3. Open invite URL → register → verify permissions

- [ ] **Step 2: Test team member invite restriction**

1. Login as admin, create a team user with limited permissions (no can_create_invites)
2. Actually, create a team user WITH can_create_invites but WITHOUT is_admin
3. Login as team user
4. Create invite → verify team user can only see/grant permissions they have

- [ ] **Step 3: Test max_uses limits**

1. Create invite with max_uses=2
2. Use it twice → verify third attempt fails
3. Create invite with max_uses=50 → verify it works
4. Create invite with max_uses=-1 → verify unlimited works

- [ ] **Step 4: Push all changes**

```bash
git add -A
git commit -m "feat: complete invite permissions system"
git push
```
