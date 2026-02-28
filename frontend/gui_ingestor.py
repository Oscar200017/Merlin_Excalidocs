import os
import csv
import json
import shutil
import signal
import hashlib
import base64
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ============================================================
# ENVIRONMENT (POR SI NO LO HAY) + CONEXIÓN A LA BBDD
# ============================================================
load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://merlin_user:merlin_pass@localhost:5432/merlin"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# ============================================================
# PERMISOS DE USUARIO
# ============================================================
PERMISSIONS = ["USER", "POWER", "EXECUTOR", "ADMIN"]  # 1 solo rol por usuario

# ============================================================
# GESTIÓN DE PASSWORDS (PBKDF2 - stdlib)
# ============================================================
PASSWORD_MIN_LEN = 6
PASSWORD_MAX_LEN = 256
PBKDF2_ITERS = 210_000


def password_ok(pw: str) -> tuple[bool, str]:
    if not pw:
        return False, "La contraseña es obligatoria."
    if len(pw) < PASSWORD_MIN_LEN:
        return False, f"La contraseña debe tener al menos {PASSWORD_MIN_LEN} caracteres."
    if len(pw) > PASSWORD_MAX_LEN:
        return False, f"La contraseña es demasiado larga (máximo {PASSWORD_MAX_LEN} caracteres)."
    return True, ""


def hash_password(pw: str) -> str:
    """
    Formato: pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITERS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        PBKDF2_ITERS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, it_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        it = int(it_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, it)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ============================================================
# BÚSQUEDA DE LA RAÍZ DEL PROYECTO POR DEFECTO
# ============================================================
def find_project_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(12):
        if (cur / "backend").exists() and (cur / "frontend").exists():
            return cur
        if (cur / ".git").exists() and (cur / "backend").exists():
            return cur
        cur = cur.parent
    return start.resolve()


# ============================================================
# PATHS/RUTAS DEL GUARDADO DE ARCHIVOS PARA LA ORDENACIÓN
# ============================================================
THIS_FILE_DIR = Path(__file__).resolve().parent
ROOT = find_project_root(THIS_FILE_DIR)  # repo root (merlin-docs/)
STORAGE = ROOT / "storage"
USERS_DIR = STORAGE / "users"
ADMIN_DIR = STORAGE / "admin"
ADMIN_USERS_JSON = ADMIN_DIR / "users_admin.json"
USERS_JSON = USERS_DIR / "users.json"

# ============================================================
# TEMAS ESPECÍFICOS APP
# ============================================================
BG_APP = "#0F172A"
BG_HEADER = "#111C33"
BG_SIDEBAR = "#0B1224"
BG_SURFACE = "#1E293B"
BG_CARD = "#101B33"

TEXT_PRIMARY = "#E5E7EB"
TEXT_SECONDARY = "#A7B0C0"
TEXT_LIGHT = "#FFFFFF"

BTN_GREEN = "#22C55E"
BTN_RED = "#EF4444"
BTN_BLUE = "#3B82F6"
BTN_SECONDARY = "#24324A"
BTN_SEC_HOVER = "#2C3B57"

ROW_EVEN = "#1E293B"
ROW_ODD = "#24324A"

# ============================================================
# AUXILIARES PARA CAMBIOS DE FORMATO Y GESTIÓN
# ============================================================
def now_str():
    return datetime.now().strftime("%d/%m/%Y_%H:%M:%S")


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    s = float(num_bytes)
    for u in units:
        if s < 1024 or u == units[-1]:
            return f"{s:.1f} {u}"
        s /= 1024
    return f"{num_bytes} B"


GB = 1024 ** 3
STORAGE_MAX_GB = 100.0
STORAGE_MAX_BYTES = int(STORAGE_MAX_GB * GB)


def dir_size_bytes(folder: Path) -> int:
    if not folder.exists():
        return 0
    total = 0
    for p in folder.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except Exception:
                pass
    return total


def format_gb(num_bytes: int) -> str:
    gb = num_bytes / GB
    if gb < 0.01 and num_bytes > 0:
        gb = 0.01
    return f"{gb:.2f} GB"


def fmt_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y_%H:%M:%S")


def file_format(p: Path) -> str:
    ext = (p.suffix or "").lstrip(".").upper()
    return ext if ext else "-"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_destination(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suf, i = dst.stem, dst.suffix, 1
    while True:
        cand = dst.with_name(f"{stem}_{i}{suf}")
        if not cand.exists():
            return cand
        i += 1


def safe_move_to_trash(src: Path, trash_dir: Path) -> Path:
    trash_dir.mkdir(parents=True, exist_ok=True)
    dst = unique_destination(trash_dir / src.name)
    shutil.move(str(src), str(dst))
    return dst


def ensure_csv_header(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "original_filename,stored_path,sha256,size_bytes,ext,category,year,last_write_time\n",
            encoding="utf-8"
        )


def _json_load_or_default(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"users": []}


def admin_json_add(user_row: dict):
    ADMIN_DIR.mkdir(parents=True, exist_ok=True)
    data = _json_load_or_default(ADMIN_USERS_JSON)

    if "users" not in data or not isinstance(data["users"], list):
        data["users"] = []

    data["users"] = [u for u in data["users"] if u.get("nickname") != user_row.get("nickname")]
    data["users"].append(user_row)

    ADMIN_USERS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def users_json_add(user_row: dict):
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    data = _json_load_or_default(USERS_JSON)

    if "users" not in data or not isinstance(data["users"], list):
        data["users"] = []

    data["users"] = [u for u in data["users"] if u.get("nickname") != user_row.get("nickname")]
    data["users"].append(user_row)

    USERS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================
# PATHS/RUTAS PARA LOS USUARIOS
# ============================================================
@dataclass
class UserPaths:
    project_root: Path
    nickname: str
    base: Path
    incoming: Path
    processed_docs: Path
    manifest: Path
    trash_incoming: Path
    trash_processed: Path


def paths_for(nickname: str) -> UserPaths:
    base = USERS_DIR / nickname
    incoming = base / "incoming"
    processed_docs = base / "processed" / "DOCS"
    manifest = base / "processed" / "manifest.csv"
    trash_incoming = incoming / "_trash"
    trash_processed = processed_docs / "_trash"
    return UserPaths(
        project_root=ROOT,
        nickname=nickname,
        base=base,
        incoming=incoming,
        processed_docs=processed_docs,
        manifest=manifest,
        trash_incoming=trash_incoming,
        trash_processed=trash_processed,
    )


def ensure_user_dirs(nickname: str) -> UserPaths:
    p = paths_for(nickname)
    p.incoming.mkdir(parents=True, exist_ok=True)
    p.processed_docs.mkdir(parents=True, exist_ok=True)
    p.trash_incoming.mkdir(parents=True, exist_ok=True)
    p.trash_processed.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(p.manifest)
    return p


# ============================================================
# ARRANQUE DE LA BASE DE DATOS + PROTOCOLO DE AUDITORÍA
# ============================================================
def db_init():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            nickname TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            contact TEXT,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """))

        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='permission'
            ) THEN
                ALTER TABLE users ADD COLUMN permission TEXT NOT NULL DEFAULT 'USER';
            END IF;
        END $$;
        """))

        conn.execute(text("UPDATE users SET permission='USER' WHERE permission IS NULL OR permission=''"))
        conn.execute(text("UPDATE users SET permission='ADMIN', is_admin=TRUE WHERE nickname='admin'"))


def db_create_user(nickname: str, email: str, contact: str, password: str, is_admin: bool = False, permission: str = "USER"):
    ph = hash_password(password)
    perm = permission if permission in PERMISSIONS else "USER"
    if is_admin:
        perm = "ADMIN"

    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO users (nickname, email, contact, password_hash, is_admin, permission)
                    VALUES (:n, :e, :c, :p, :a, :perm)
            """),
            {"n": nickname, "e": email, "c": contact, "p": ph, "a": is_admin, "perm": perm}
        )

    user_row = {
        "nickname": nickname,
        "email": email,
        "contact": contact,
        "password_hash": ph,
        "is_admin": is_admin,
        "permission": perm,
        "created_at": now_str(),
    }
    admin_json_add(user_row)
    users_json_add(user_row)


def db_get_user_by_login(identifier: str):
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT id, nickname, email, contact, password_hash, is_admin, permission
                FROM users
                WHERE email = :x OR nickname = :x
            """),
            {"x": identifier}
        ).mappings().first()
        return row


def db_update_password(user_id: int, new_password: str):
    ph = hash_password(new_password)
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET password_hash=:p WHERE id=:i"), {"p": ph, "i": user_id})


def db_get_all_users():
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, nickname, email, contact, is_admin, permission, created_at
            FROM users
            ORDER BY created_at DESC
        """)).mappings().all()
        return rows


def db_update_user_permission(user_id: int, new_perm: str):
    perm = new_perm if new_perm in PERMISSIONS else "USER"
    with engine.begin() as conn:
        if perm == "ADMIN":
            conn.execute(
                text("UPDATE users SET permission=:p, is_admin=TRUE WHERE id=:i"),
                {"p": perm, "i": user_id}
            )
        else:
            conn.execute(
                text("UPDATE users SET permission=:p, is_admin=FALSE WHERE id=:i AND nickname <> 'admin'"),
                {"p": perm, "i": user_id}
            )


def sync_users_storage_from_db():
    try:
        rows = db_get_all_users()
    except Exception:
        return

    for r in rows:
        nick = (r.get("nickname") or "").strip()
        if not nick:
            continue

        try:
            ensure_user_dirs(nick)
        except Exception:
            pass

        try:
            users_json_add({
                "nickname": nick,
                "email": r.get("email") or "",
                "contact": r.get("contact") or "",
                "password_hash": "",
                "is_admin": bool(r.get("is_admin")),
                "permission": r.get("permission") or "USER",
                "created_at": str(r.get("created_at") or now_str()),
            })
        except Exception:
            pass


def ensure_default_admin():
    admin_nick = "admin"
    admin_email = "admin@local"
    admin_pw = "administrador"
    admin_contact = "Admin"

    ph = hash_password(admin_pw)

    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT id FROM users WHERE nickname=:n LIMIT 1"),
            {"n": admin_nick}
        ).first()

        if not exists:
            conn.execute(
                text("""INSERT INTO users (nickname, email, contact, password_hash, is_admin, permission)
                        VALUES (:n, :e, :c, :p, TRUE, 'ADMIN')
                """),
                {"n": admin_nick, "e": admin_email, "c": admin_contact, "p": ph}
            )
        else:
            conn.execute(
                text("""
                    UPDATE users
                    SET password_hash=:p,
                        is_admin=TRUE,
                        permission='ADMIN',
                        email=COALESCE(email, :e),
                        contact=COALESCE(contact, :c)
                    WHERE nickname=:n
                """),
                {"p": ph, "n": admin_nick, "e": admin_email, "c": admin_contact}
            )

    user_row = {
        "nickname": admin_nick,
        "email": admin_email,
        "contact": admin_contact,
        "password_hash": ph,
        "is_admin": True,
        "permission": "ADMIN",
        "created_at": now_str(),
    }
    try:
        admin_json_add(user_row)
    except Exception:
        pass
    try:
        users_json_add(user_row)
    except Exception:
        pass
    try:
        ensure_user_dirs(admin_nick)
    except Exception:
        pass


# ============================================================
# COMPONENTES GRÁFICOS EN LA INTERFAZ
# ============================================================
class FlatButton(tk.Label):
    def __init__(
        self,
        master,
        text,
        bg_color,
        hover_color=None,
        text_color=TEXT_LIGHT,
        command=None,
        font=("Segoe UI", 9, "bold"),
        anchor="center",
        **kwargs
    ):
        super().__init__(
            master,
            text=text,
            bg=bg_color,
            fg=text_color,
            font=font,
            cursor="hand2",
            pady=7,
            padx=14,
            anchor=anchor,
            **kwargs
        )
        self.bg_color = bg_color
        self.hover_color = hover_color if hover_color else bg_color
        self.command = command
        self.bind("<Enter>", lambda e: self.config(bg=self.hover_color))
        self.bind("<Leave>", lambda e: self.config(bg=self.bg_color))
        self.bind("<Button-1>", lambda e: self.command() if self.command else None)


class Card(tk.Frame):
    def __init__(self, master, title: str):
        super().__init__(master, bg=BG_CARD, highlightthickness=1, highlightbackground="#1F2A44")
        tk.Label(self, text=title, bg=BG_CARD, fg=TEXT_PRIMARY, font=("Segoe UI", 12, "bold")).pack(
            anchor="w", padx=16, pady=(14, 10)
        )


# ============================================================
# MODULADO DE LA APP
# ============================================================
class ExcalidocsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        db_init()
        ensure_default_admin()
        sync_users_storage_from_db()

        self.title("Excalidocs")
        self.geometry("1320x780")
        self.minsize(1150, 650)
        self.configure(bg=BG_APP)

        self.current_user = None
        self.paths: UserPaths | None = None

        self.sidebar_expanded = False
        self._toggle_lock = False
        self._sort_state = {}
        self._rowmeta = {}

        self._perm_combo = None  # combobox overlay en usuarios

        self.protocol("WM_DELETE_WINDOW", self.on_exit)
        try:
            signal.signal(signal.SIGINT, lambda *_: self.on_exit())
        except Exception:
            pass

        self._setup_styles()

        self.root_container = tk.Frame(self, bg=BG_APP)
        self.root_container.pack(fill="both", expand=True)

        self.show_start_screen()

    def _setup_styles(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(
            "Treeview",
            background=BG_SURFACE,
            fieldbackground=BG_SURFACE,
            foreground=TEXT_PRIMARY,
            rowheight=34,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map(
            "Treeview",
            background=[("selected", "#334155")],
            foreground=[("selected", TEXT_PRIMARY)],
        )
        style.configure(
            "Treeview.Heading",
            background="#16213A",
            foreground=TEXT_SECONDARY,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=6,
        )
        style.map("Treeview.Heading", background=[("active", "#1B2A4A")])

    def on_exit(self):
        try:
            self.destroy()
        except Exception:
            pass

    def _clear_root(self):
        for w in self.root_container.winfo_children():
            w.destroy()

    # ============================================================
    # START SCREEN
    # ============================================================
    def show_start_screen(self):
        self._clear_root()
        self.current_user = None
        self.paths = None

        header = tk.Frame(self.root_container, bg=BG_HEADER, height=70)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text="🧙 Excalidocs", bg=BG_HEADER, fg=TEXT_PRIMARY, font=("Segoe UI", 16, "bold")).pack(
            side="left", padx=22
        )

        body = tk.Frame(self.root_container, bg=BG_APP)
        body.pack(fill="both", expand=True, padx=26, pady=26)

        body.grid_columnconfigure(0, weight=1, uniform="cards")
        body.grid_columnconfigure(1, weight=1, uniform="cards")
        body.grid_rowconfigure(0, weight=1)

        reg = Card(body, "Registro")
        reg.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.reg_nick = self._field(reg, "Nickname")
        self.reg_email = self._field(reg, "Email")
        self.reg_contact = self._field(reg, "Contacto (opcional)")
        self.reg_pass = self._field(reg, "Contraseña", show="*")

        FlatButton(reg, "Crear cuenta", BTN_GREEN, "#16A34A", command=self.on_register).pack(
            anchor="e", padx=16, pady=(14, 16)
        )

        log = Card(body, "Login")
        log.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        self.log_email = self._field(log, "Email o Nickname")
        self.log_pass = self._field(log, "Contraseña", show="*")

        FlatButton(log, "Entrar", BTN_BLUE, "#2563EB", command=self.on_login).pack(
            anchor="e", padx=16, pady=(14, 16)
        )

        tk.Label(
            self.root_container,
            text="Datos en PostgreSQL + JSON local. Admin por defecto: admin/administrador",
            bg=BG_APP, fg=TEXT_SECONDARY, font=("Segoe UI", 9)
        ).pack(side="bottom", pady=(0, 14))

    def _field(self, parent, label: str, show: str | None = None):
        wrap = tk.Frame(parent, bg=BG_CARD)
        wrap.pack(fill="x", padx=16, pady=7)
        tk.Label(wrap, text=label, bg=BG_CARD, fg=TEXT_SECONDARY, font=("Segoe UI", 9)).pack(anchor="w")
        e = tk.Entry(
            wrap,
            show=show if show else "",
            bg="#0B1224",
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#1F2A44"
        )
        e.pack(fill="x", pady=(4, 0), ipady=6)
        return e

    def on_register(self):
        nickname = self.reg_nick.get().strip()
        email = self.reg_email.get().strip()
        contact = self.reg_contact.get().strip()
        password = self.reg_pass.get().strip()

        if not nickname or not email:
            messagebox.showerror("Registro", "Nickname y Email son obligatorios.")
            return

        ok, msg = password_ok(password)
        if not ok:
            messagebox.showerror("Registro", msg)
            return

        try:
            db_create_user(nickname, email, contact, password, is_admin=False, permission="USER")
        except Exception as e:
            messagebox.showerror("Registro", f"No se pudo crear el usuario:\n{e}")
            return

        ensure_user_dirs(nickname)

        messagebox.showinfo("OK", "Cuenta creada. Ahora haz login.")
        self.reg_pass.delete(0, tk.END)

    def on_login(self):
        identifier = self.log_email.get().strip()
        password = self.log_pass.get().strip()

        if not identifier:
            messagebox.showerror("Login", "Email o Nickname obligatorio.")
            return

        ok, msg = password_ok(password)
        if not ok:
            messagebox.showerror("Login", msg)
            return

        row = db_get_user_by_login(identifier)
        if not row:
            messagebox.showerror("Login", "Usuario no encontrado.")
            return

        if not verify_password(password, row["password_hash"]):
            messagebox.showerror("Login", "Contraseña incorrecta.")
            return

        self.current_user = {
            "id": row["id"],
            "nickname": row["nickname"],
            "email": row["email"],
            "contact": row["contact"] or "",
            "is_admin": bool(row["is_admin"]),
            "permission": row.get("permission") or "USER"
        }

        self.paths = ensure_user_dirs(self.current_user["nickname"])
        self.show_main_app()

    # ============================================================
    # MUESTREO DE LA APP PRINCIPAL Y SUS COMPONENTES
    # ============================================================
    def show_main_app(self):
        self._clear_root()

        self.header = tk.Frame(self.root_container, bg=BG_HEADER, height=55)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        self.btn_menu = tk.Label(self.header, text="☰", font=("Segoe UI", 16),
                                 bg=BG_HEADER, fg=TEXT_PRIMARY, cursor="hand2")
        self.btn_menu.pack(side="left", padx=(20, 10))
        self.btn_menu.bind("<Button-1>", self.toggle_sidebar)

        tk.Label(self.header, text="🧙 Merlin's Excalidocs", font=("Segoe UI", 13, "bold"),
                 bg=BG_HEADER, fg=TEXT_PRIMARY).pack(side="left")

        tk.Label(self.header, text=f"Conectado como: {self.current_user['nickname']} ({self.current_user.get('permission','USER')})",
                 bg=BG_HEADER, fg=TEXT_SECONDARY, font=("Segoe UI", 10)).pack(side="right", padx=22)

        self.main_container = tk.Frame(self.root_container, bg=BG_APP)
        self.main_container.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.main_container, bg=BG_SIDEBAR, width=240)
        self.sidebar.pack_propagate(False)

        FlatButton(self.sidebar, "📋 Panel de Control", BG_SIDEBAR, "#121B33",
                   text_color=TEXT_PRIMARY, command=self.show_dashboard, anchor="w").pack(fill="x", pady=(20, 5))
        FlatButton(self.sidebar, "🧾 Logs", BG_SIDEBAR, "#121B33",
                   text_color=TEXT_PRIMARY, command=self.show_logs, anchor="w").pack(fill="x", pady=5)
        FlatButton(self.sidebar, "🗑 Papelera", BG_SIDEBAR, "#121B33",
                   text_color=TEXT_PRIMARY, command=self.show_trash, anchor="w").pack(fill="x", pady=5)
        FlatButton(self.sidebar, "👤 Cuenta", BG_SIDEBAR, "#121B33",
                   text_color=TEXT_PRIMARY, command=self.show_account, anchor="w").pack(fill="x", pady=5)

        if self.current_user.get("is_admin"):
            FlatButton(self.sidebar, "👥 Usuarios", BG_SIDEBAR, "#121B33",
                       text_color=TEXT_PRIMARY, command=self.show_users, anchor="w").pack(fill="x", pady=5)

        storage_wrap = tk.Frame(self.sidebar, bg=BG_SIDEBAR)
        storage_wrap.pack(side="bottom", fill="x", padx=12, pady=12)

        tk.Label(
            storage_wrap,
            text="Almacenamiento",
            bg=BG_SIDEBAR,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w")

        self.storage_var = tk.IntVar(value=0)
        self.storage_bar = ttk.Progressbar(
            storage_wrap,
            orient="horizontal",
            mode="determinate",
            maximum=STORAGE_MAX_BYTES,
            variable=self.storage_var
        )
        self.storage_bar.pack(fill="x", pady=(6, 6))

        self.storage_label = tk.Label(
            storage_wrap,
            text=f"0.00 GB / {STORAGE_MAX_GB:.2f} GB",
            bg=BG_SIDEBAR,
            fg=TEXT_PRIMARY,
            font=("Segoe UI", 9)
        )
        self.storage_label.pack(anchor="w")

        self.content_area = tk.Frame(self.main_container, bg=BG_APP)
        self.content_area.pack(side="left", fill="both", expand=True)

        self.view_dashboard = tk.Frame(self.content_area, bg=BG_APP)
        self.view_logs = tk.Frame(self.content_area, bg=BG_APP)
        self.view_trash = tk.Frame(self.content_area, bg=BG_APP)
        self.view_account = tk.Frame(self.content_area, bg=BG_APP)
        self.view_users = tk.Frame(self.content_area, bg=BG_APP)

        self._build_dashboard_view()
        self._build_logs_view()
        self._build_trash_view()
        self._build_account_view()
        if self.current_user.get("is_admin"):
            self._build_users_view()

        self.update_storage_bar()
        self.show_dashboard()

    def toggle_sidebar(self, event=None):
        if self._toggle_lock:
            return
        self._toggle_lock = True
        self.after(180, lambda: setattr(self, "_toggle_lock", False))

        if self.sidebar_expanded:
            self.sidebar.pack_forget()
            self.sidebar_expanded = False
        else:
            self.sidebar.pack(side="left", fill="y", before=self.content_area)
            self.sidebar_expanded = True

    def _hide_all_views(self):
        self.view_dashboard.pack_forget()
        self.view_logs.pack_forget()
        self.view_trash.pack_forget()
        self.view_account.pack_forget()
        self.view_users.pack_forget()

    def _tree_meta(self, tree: ttk.Treeview):
        return self._rowmeta.setdefault(id(tree), {})

    def _attach_sorting(self, tree: ttk.Treeview, cols: list[str]):
        for col in cols:
            tree.heading(col, command=lambda c=col, t=tree: self.sort_tree(t, c))

    def sort_tree(self, tree: ttk.Treeview, col: str):
        key = (id(tree), col)
        desc = self._sort_state.get(key, False)
        meta = self._tree_meta(tree)

        items = list(tree.get_children(""))

        def sort_key(iid):
            m = meta.get(iid, {})
            if col in ("name", "file", "nickname", "email", "contact"):
                return (tree.set(iid, col) or "").lower()
            if col in ("size",):
                return m.get("size_bytes", 0)
            if col in ("format",):
                return (m.get("format", "")).lower()
            if col in ("date", "created_at"):
                return m.get("mtime", 0.0)
            return (tree.set(iid, col) or "").lower()

        items.sort(key=sort_key, reverse=desc)
        for i, iid in enumerate(items):
            tree.move(iid, "", i)
        self._sort_state[key] = not desc

    def update_storage_bar(self):
        if not self.paths:
            return

        processed_bytes = dir_size_bytes(self.paths.processed_docs)
        trash_bytes = dir_size_bytes(self.paths.trash_incoming) + dir_size_bytes(self.paths.trash_processed)

        used = processed_bytes + trash_bytes
        used_clamped = min(used, STORAGE_MAX_BYTES)

        self.storage_var.set(used_clamped)
        self.storage_label.config(text=f"{format_gb(used)} / {STORAGE_MAX_GB:.2f} GB")

    def _open_folder(self, path: Path):
        try:
            path.mkdir(parents=True, exist_ok=True)  # ✅ si falta, la crea (para no petar)
            if os.name == "nt":
                os.startfile(str(path))
            else:
                import subprocess
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir:\n{e}")

    # ============================================================
    # TAREAS Y ADICIÓN DE MODIFICACIONES
    # ============================================================
    def show_dashboard(self):
        self._hide_all_views()
        self.view_dashboard.pack(fill="both", expand=True)
        self.refresh_dashboard()

    def _build_dashboard_view(self):
        assert self.paths is not None

        toolbar = tk.Frame(self.view_dashboard, bg=BG_APP)
        toolbar.pack(fill="x", padx=20, pady=15)

        left_tools = tk.Frame(toolbar, bg=BG_APP)
        left_tools.pack(side="left")

        FlatButton(left_tools, "Añadir Archivos", BTN_GREEN, "#16A34A", command=self.import_files).pack(
            side="left", padx=(0, 10)
        )
        FlatButton(left_tools, "Eliminar Todos", BTN_RED, "#DC2626", command=self.delete_all_incoming).pack(
            side="left"
        )

        right_tools = tk.Frame(toolbar, bg=BG_APP)
        right_tools.pack(side="right")

        FlatButton(right_tools, "Refrescar", BTN_SECONDARY, BTN_SEC_HOVER, text_color=TEXT_PRIMARY,
                   command=self.refresh_dashboard).pack(side="left", padx=10)
        FlatButton(right_tools, "Revertir Procesados", BTN_SECONDARY, BTN_SEC_HOVER, text_color=TEXT_PRIMARY,
                   command=self.revert_to_incoming).pack(side="left", padx=10)
        FlatButton(right_tools, "Ver Carpeta Destino", BTN_SECONDARY, BTN_SEC_HOVER, text_color=TEXT_PRIMARY,
                   command=self.open_docs_folder).pack(side="left", padx=10)

        FlatButton(right_tools, "Ordenar seleccionados", BTN_BLUE, "#2563EB",
                   command=self.order_selected_incoming).pack(side="left", padx=(10, 0))
        FlatButton(right_tools, "Ordenar todos", BTN_BLUE, "#2563EB",
                   command=self.order_all_incoming).pack(side="left", padx=(10, 0))

        split_container = tk.Frame(self.view_dashboard, bg=BG_APP)
        split_container.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        split_container.grid_columnconfigure(0, weight=1, uniform="cols")
        split_container.grid_columnconfigure(1, weight=1, uniform="cols")
        split_container.grid_rowconfigure(0, weight=1)

        left_panel = tk.Frame(split_container, bg=BG_SURFACE)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        top_l = tk.Frame(left_panel, bg=BG_SURFACE)
        top_l.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(top_l, text="📥 Documentos a Ordenar", font=("Segoe UI", 11, "bold"),
                 bg=BG_SURFACE, fg=TEXT_PRIMARY).pack(side="left")

        self.search_in_var = tk.StringVar(value="")
        self.search_in = tk.Entry(top_l, textvariable=self.search_in_var,
                                  bg="#0B1224", fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                                  relief="flat", highlightthickness=1, highlightbackground="#1F2A44", width=26)
        self.search_in.pack(side="right", padx=(0, 8), ipady=5)
        self.search_in.bind("<KeyRelease>", lambda e: self.refresh_dashboard())

        left_table = tk.Frame(left_panel, bg=BG_SURFACE)
        left_table.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ("name", "size", "format", "date", "action")
        self.tree_in = ttk.Treeview(left_table, columns=cols, show="headings", selectmode="extended")
        self.tree_in.heading("name", text="Nombre", anchor="w")
        self.tree_in.heading("size", text="Tamaño", anchor="center")
        self.tree_in.heading("format", text="Formato", anchor="center")
        self.tree_in.heading("date", text="Fecha de Modificación", anchor="w")
        self.tree_in.heading("action", text="Acción", anchor="center")

        self.tree_in.column("name", width=360, minwidth=220, stretch=True, anchor="w")
        self.tree_in.column("size", width=110, minwidth=90, stretch=True, anchor="center")
        self.tree_in.column("format", width=110, minwidth=90, stretch=True, anchor="center")
        self.tree_in.column("date", width=190, minwidth=150, stretch=True, anchor="w")
        self.tree_in.column("action", width=90, minwidth=70, stretch=False, anchor="center")

        self.tree_in.pack(side="left", fill="both", expand=True)

        sy = ttk.Scrollbar(left_table, orient="vertical", command=self.tree_in.yview)
        sy.pack(side="right", fill="y")
        self.tree_in.configure(yscrollcommand=sy.set)

        sx = ttk.Scrollbar(left_panel, orient="horizontal", command=self.tree_in.xview)
        sx.pack(side="bottom", fill="x")
        self.tree_in.configure(xscrollcommand=sx.set)

        self.tree_in.tag_configure("even", background=ROW_EVEN)
        self.tree_in.tag_configure("odd", background=ROW_ODD)
        self.tree_in.bind("<ButtonRelease-1>", self.on_tree_in_click)
        self._attach_sorting(self.tree_in, list(cols))

        right_panel = tk.Frame(split_container, bg=BG_SURFACE)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        top_r = tk.Frame(right_panel, bg=BG_SURFACE)
        top_r.pack(fill="x", padx=10, pady=(10, 5))
        tk.Label(top_r, text="Documentos Ya Ordenados", font=("Segoe UI", 11, "bold"),
                 bg=BG_SURFACE, fg=TEXT_PRIMARY).pack(side="left")

        self.search_out_var = tk.StringVar(value="")
        self.search_out = tk.Entry(top_r, textvariable=self.search_out_var,
                                   bg="#0B1224", fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                                   relief="flat", highlightthickness=1, highlightbackground="#1F2A44", width=26)
        self.search_out.pack(side="right", padx=(0, 8), ipady=5)
        self.search_out.bind("<KeyRelease>", lambda e: self.refresh_dashboard())

        right_table = tk.Frame(right_panel, bg=BG_SURFACE)
        right_table.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree_out = ttk.Treeview(right_table, columns=cols, show="headings", selectmode="extended")
        for c, t in [("name", "Nombre"), ("size", "Tamaño"), ("format", "Formato"), ("date", "Fecha de Modificación"),
                     ("action", "Acción")]:
            self.tree_out.heading(c, text=t)

        self.tree_out.column("name", width=360, minwidth=220, stretch=True, anchor="w")
        self.tree_out.column("size", width=110, minwidth=90, stretch=True, anchor="center")
        self.tree_out.column("format", width=110, minwidth=90, stretch=True, anchor="center")
        self.tree_out.column("date", width=190, minwidth=150, stretch=True, anchor="w")
        self.tree_out.column("action", width=90, minwidth=70, stretch=False, anchor="center")

        self.tree_out.pack(side="left", fill="both", expand=True)

        sy2 = ttk.Scrollbar(right_table, orient="vertical", command=self.tree_out.yview)
        sy2.pack(side="right", fill="y")
        self.tree_out.configure(yscrollcommand=sy2.set)

        sx2 = ttk.Scrollbar(right_panel, orient="horizontal", command=self.tree_out.xview)
        sx2.pack(side="bottom", fill="x")
        self.tree_out.configure(xscrollcommand=sx2.set)

        self.tree_out.tag_configure("even", background=ROW_EVEN)
        self.tree_out.tag_configure("odd", background=ROW_ODD)
        self.tree_out.bind("<ButtonRelease-1>", self.on_tree_out_click)
        self._attach_sorting(self.tree_out, list(cols))

    def on_tree_in_click(self, event):
        region = self.tree_in.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree_in.identify_column(event.x)
        if col != "#5":
            return
        iid = self.tree_in.identify_row(event.y)
        if not iid:
            return
        name = str(self.tree_in.item(iid, "values")[0]).strip()
        self.delete_single_incoming_file(name)

    def on_tree_out_click(self, event):
        region = self.tree_out.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree_out.identify_column(event.x)
        if col != "#5":
            return
        iid = self.tree_out.identify_row(event.y)
        if not iid:
            return
        name = str(self.tree_out.item(iid, "values")[0]).strip()
        self.delete_single_processed_file(name)

    def refresh_dashboard(self):
        assert self.paths is not None
        for t in (self.tree_in, self.tree_out):
            for iid in t.get_children():
                t.delete(iid)
            self._tree_meta(t).clear()

        q_in = (self.search_in_var.get() if hasattr(self, "search_in_var") else "").strip().lower()
        q_out = (self.search_out_var.get() if hasattr(self, "search_out_var") else "").strip().lower()

        in_files = sorted([p for p in self.paths.incoming.iterdir() if p.is_file()], key=lambda p: p.name.lower())
        meta_in = self._tree_meta(self.tree_in)

        idx = 0
        for p in in_files:
            if q_in and q_in not in p.name.lower():
                continue
            st = p.stat()
            size_b = st.st_size
            mtime = st.st_mtime
            fmt = file_format(p)
            iid = str(p)
            tag = "odd" if idx % 2 else "even"
            self.tree_in.insert("", tk.END, iid=iid,
                                values=(p.name, human_size(size_b), fmt, fmt_mtime(mtime), "Borrar"),
                                tags=(tag,))
            meta_in[iid] = {"name": p.name, "size_bytes": size_b, "mtime": mtime, "format": fmt}
            idx += 1

        if self.paths.processed_docs.exists():
            out_files = sorted([p for p in self.paths.processed_docs.rglob("*") if p.is_file()],
                               key=lambda p: p.stat().st_mtime, reverse=True)

            meta_out = self._tree_meta(self.tree_out)
            idx = 0
            for p in out_files:
                if q_out and q_out not in p.name.lower():
                    continue
                st = p.stat()
                size_b = st.st_size
                mtime = st.st_mtime
                fmt = file_format(p)
                iid = str(p)
                tag = "odd" if idx % 2 else "even"
                self.tree_out.insert("", tk.END, iid=iid,
                                     values=(p.name, human_size(size_b), fmt, fmt_mtime(mtime), "Borrar"),
                                     tags=(tag,))
                meta_out[iid] = {"name": p.name, "size_bytes": size_b, "mtime": mtime, "format": fmt}
                idx += 1

        self.update_storage_bar()

    def _organize_file(self, src: Path):
        assert self.paths is not None
        if not src.exists() or not src.is_file():
            return

        st = src.stat()
        ext = file_format(src)
        dt = datetime.fromtimestamp(st.st_mtime)
        year = dt.year
        month = f"{dt.month:02d}"
        category = f"{ext}/{year}/{month}"

        dst_dir = self.paths.processed_docs / ext / str(year) / month
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = unique_destination(dst_dir / src.name)

        h = sha256_file(src)
        size_b = st.st_size
        last_write = datetime.fromtimestamp(st.st_mtime).isoformat()

        shutil.move(str(src), str(dst))

        ensure_csv_header(self.paths.manifest)
        with open(self.paths.manifest, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow([src.name, str(dst), h, size_b, ext, category, year, last_write])

    def order_all_incoming(self):
        assert self.paths is not None
        files = [p for p in self.paths.incoming.iterdir() if p.is_file()]
        if not files:
            messagebox.showinfo("Info", "No hay archivos en incoming.")
            return
        for p in files:
            self._organize_file(p)
        self.refresh_dashboard()

    def order_selected_incoming(self):
        assert self.paths is not None
        sel = self.tree_in.selection()
        if not sel:
            messagebox.showinfo("Info", "Selecciona archivos en la lista de la izquierda (Ctrl+Click).")
            return
        count = 0
        for iid in sel:
            p = Path(iid)
            if p.exists() and p.is_file():
                self._organize_file(p)
                count += 1
        messagebox.showinfo("OK", f"Ordenados: {count}")
        self.refresh_dashboard()

    # ============================================================
    # LOGS
    # ============================================================
    def show_logs(self):
        self._hide_all_views()
        self.view_logs.pack(fill="both", expand=True)
        self.refresh_logs()

    def _build_logs_view(self):
        header = tk.Frame(self.view_logs, bg=BG_APP)
        header.pack(fill="x", padx=30, pady=20)

        tk.Label(header, text="Audit Trail", bg=BG_APP, fg=TEXT_PRIMARY,
                 font=("Segoe UI", 14, "bold")).pack(side="left")

        btns = tk.Frame(header, bg=BG_APP)
        btns.pack(side="right")

        FlatButton(btns, "Eliminar seleccionados", BTN_RED, "#DC2626",
                   command=self.delete_selected_logs).pack(side="left", padx=10)
        FlatButton(btns, "Eliminar logs", BTN_RED, "#DC2626",
                   command=self.delete_all_logs).pack(side="left", padx=10)
        FlatButton(btns, "Recargar", BTN_SECONDARY, BTN_SEC_HOVER, text_color=TEXT_PRIMARY,
                   command=self.refresh_logs).pack(side="left")

        table = tk.Frame(self.view_logs, bg=BG_SURFACE)
        table.pack(fill="both", expand=True, padx=30, pady=(0, 30))

        cols = ("file", "cat", "size", "date")
        self.tree_logs = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        self.tree_logs.heading("file", text="Archivo Original", anchor="w")
        self.tree_logs.heading("cat", text="Categoría Asignada", anchor="center")
        self.tree_logs.heading("size", text="Tamaño Original", anchor="center")
        self.tree_logs.heading("date", text="Fecha de Modificación", anchor="w")

        self.tree_logs.column("file", width=520, minwidth=260, stretch=True, anchor="w")
        self.tree_logs.column("cat", width=180, minwidth=120, stretch=True, anchor="center")
        self.tree_logs.column("size", width=140, minwidth=90, stretch=True, anchor="center")
        self.tree_logs.column("date", width=220, minwidth=140, stretch=True, anchor="w")

        self.tree_logs.pack(side="left", fill="both", expand=True)

        sy = ttk.Scrollbar(table, orient="vertical", command=self.tree_logs.yview)
        sy.pack(side="right", fill="y")
        self.tree_logs.configure(yscrollcommand=sy.set)

        self.tree_logs.tag_configure("even", background=ROW_EVEN)
        self.tree_logs.tag_configure("odd", background=ROW_ODD)

        #Click normal (sin release) para abrir carpeta
        self.tree_logs.bind("<Button-1>", self.on_logs_category_click)

        self._attach_sorting(self.tree_logs, list(cols))

    def refresh_logs(self):
        assert self.paths is not None
        for iid in self.tree_logs.get_children():
            self.tree_logs.delete(iid)
        self._tree_meta(self.tree_logs).clear()

        ensure_csv_header(self.paths.manifest)
        with open(self.paths.manifest, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            rows = list(r)

        if not rows:
            self.tree_logs.insert("", tk.END, values=("No hay logs", "-", "-", "-"))
            return

        meta = self._tree_meta(self.tree_logs)
        idx = 0
        for row in rows:
            sha = (row.get("sha256") or "").strip()
            iid = sha if sha else f"row_{idx}"

            size_b = int(row.get("size_bytes") or 0)
            ext = (row.get("ext") or "-")
            year = str(row.get("year") or "-")

            stored_path = (row.get("stored_path") or "").strip()

            month = "--"
            if stored_path:
                try:
                    sp = Path(stored_path)
                    parts = list(sp.parts)
                    for i in range(len(parts) - 3):
                        if parts[i].upper() == ext.upper() and parts[i + 1] == year and parts[i + 2].isdigit() and len(parts[i + 2]) == 2:
                            month = parts[i + 2]
                            break
                except Exception:
                    pass

            if month == "--":
                try:
                    lw_tmp = row.get("last_write_time") or ""
                    clean = lw_tmp.split("+")[0].split(".")[0]
                    dt_tmp = datetime.fromisoformat(clean)
                    month = f"{dt_tmp.month:02d}"
                except Exception:
                    pass

            cat = f"{ext}/{year}/{month}"

            lw = row.get("last_write_time") or "-"
            dt_str = lw
            dt_ts = 0.0
            try:
                clean = lw.split("+")[0].split(".")[0]
                dt = datetime.fromisoformat(clean)
                dt_str = dt.strftime("%d/%m/%Y_%H:%M:%S")
                dt_ts = dt.timestamp()
            except Exception:
                pass

            tag = "odd" if idx % 2 else "even"
            self.tree_logs.insert("", tk.END, iid=iid,
                                  values=(row.get("original_filename", "-"), cat, human_size(size_b), dt_str),
                                  tags=(tag,))
            meta[iid] = {
                "name": row.get("original_filename", "-"),
                "size_bytes": size_b,
                "format": ext,
                "mtime": dt_ts,
                "stored_path": stored_path,
            }
            idx += 1

    def delete_all_logs(self):
        assert self.paths is not None
        if not messagebox.askyesno("Eliminar logs", "¿Borrar TODOS los logs del usuario actual?"):
            return
        ensure_csv_header(self.paths.manifest)
        self.paths.manifest.write_text(
            "original_filename,stored_path,sha256,size_bytes,ext,category,year,last_write_time\n",
            encoding="utf-8"
        )
        self.refresh_logs()

    def delete_selected_logs(self):
        assert self.paths is not None
        sel = self.tree_logs.selection()
        if not sel:
            messagebox.showinfo("Info", "No hay filas seleccionadas.")
            return
        if not messagebox.askyesno("Eliminar seleccionados", f"¿Eliminar {len(sel)} entradas del log?"):
            return

        with open(self.paths.manifest, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            rows = list(r)
            fieldnames = r.fieldnames or ["original_filename", "stored_path", "sha256", "size_bytes", "ext", "category", "year", "last_write_time"]

        sel_sha = {x for x in sel if x and not x.startswith("row_")}
        if sel_sha:
            rows = [rw for rw in rows if (rw.get("sha256") or "").strip() not in sel_sha]
        else:
            idx_remove = set()
            for x in sel:
                if x.startswith("row_"):
                    try:
                        idx_remove.add(int(x.split("_", 1)[1]))
                    except Exception:
                        pass
            rows = [rw for i, rw in enumerate(rows) if i not in idx_remove]

        with open(self.paths.manifest, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

        self.refresh_logs()

    def on_logs_category_click(self, event):
        if not self.paths:
            return

        region = self.tree_logs.identify("region", event.x, event.y)
        if region != "cell":
            return

        col_id = self.tree_logs.identify_column(event.x)  # "#1", "#2", ...
        cols = list(self.tree_logs["columns"])            # ("file","cat","size","date")
        try:
            col_idx = int(col_id.replace("#", "")) - 1
        except Exception:
            return
        if col_idx < 0 or col_idx >= len(cols):
            return
        if cols[col_idx] != "cat":
            return

        iid = self.tree_logs.identify_row(event.y)
        if not iid:
            return

        values = self.tree_logs.item(iid, "values")
        if not values or values[0] in ("No hay logs", "-", ""):
            return

        filename = str(values[0]).strip()
        cat = str(values[1]).strip()

        meta = self._tree_meta(self.tree_logs).get(iid, {})
        stored_path_raw = (meta.get("stored_path") or "")

        # 1) Sanitiza stored_path
        sp_clean = (
            stored_path_raw
            .replace("\ufeff", "")
            .replace("\r", "")
            .replace("\n", "")
            .replace("\t", "")
            .strip()
            .strip('"')
            .strip("'")
        )

        # 2) Si stored_path existe como fichero -> abre su carpeta
        if sp_clean:
            try:
                sp = Path(sp_clean)
                if sp.exists():
                    self._open_folder(sp.parent)
                    return
                #NUEVO: si el fichero no existe pero la carpeta sí, abre la carpeta igual
                if sp.parent.exists():
                    self._open_folder(sp.parent)
                    return
            except Exception:
                pass

        # 3) Busca el fichero real en processed_docs
        try:
            if self.paths.processed_docs.exists() and filename:
                matches = [p for p in self.paths.processed_docs.rglob(filename) if p.is_file()]
                if matches:
                    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    self._open_folder(matches[0].parent)
                    return
        except Exception:
            pass

        # 4) Fallback por categoría EXT/YYYY/MM
        parts = [p.strip() for p in cat.split("/") if p.strip()]
        if len(parts) >= 3:
            ext = parts[0].upper()
            year = parts[1]
            month = parts[2]

            folder = self.paths.processed_docs / ext / year / month

            #NUEVO: crea la carpeta si no existe, y ábrela
            try:
                folder.mkdir(parents=True, exist_ok=True)
                self._open_folder(folder)
                return
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo crear/abrir la carpeta:\n{folder}\n\n{e}")
                return

        messagebox.showinfo(
            "Info",
            (
                "No existe la carpeta asociada a este log.\n\n"
                f"stored_path (raw): {stored_path_raw or '(vacío)'}\n"
                f"stored_path (clean): {sp_clean or '(vacío)'}\n"
                f"cat: {cat}\n"
                f"filename: {filename}"
            )
        )

    # ============================================================
    # GESTIÓN DEL ELIMINADO DE DOCUMENTACIÓN Y ARCHIVOS
    # ============================================================
    def show_trash(self):
        self._hide_all_views()
        self.view_trash.pack(fill="both", expand=True)
        self.refresh_trash()

    def _build_trash_view(self):
        header = tk.Frame(self.view_trash, bg=BG_APP)
        header.pack(fill="x", padx=30, pady=20)

        tk.Label(header, text="Papelera", bg=BG_APP, fg=TEXT_PRIMARY, font=("Segoe UI", 14, "bold")).pack(side="left")

        btns = tk.Frame(header, bg=BG_APP)
        btns.pack(side="right")

        FlatButton(btns, "Restaurar seleccionados", BTN_BLUE, "#2563EB", command=self.trash_restore_selected).pack(side="left", padx=10)
        FlatButton(btns, "Eliminar seleccionados", BTN_RED, "#DC2626", command=self.trash_delete_selected).pack(side="left", padx=10)
        FlatButton(btns, "Vaciar papelera", BTN_RED, "#DC2626", command=self.trash_empty).pack(side="left", padx=10)
        FlatButton(btns, "Recargar", BTN_SECONDARY, BTN_SEC_HOVER, text_color=TEXT_PRIMARY, command=self.refresh_trash).pack(side="left")

        table = tk.Frame(self.view_trash, bg=BG_SURFACE)
        table.pack(fill="both", expand=True, padx=30, pady=(0, 30))

        cols = ("restore", "file", "origin", "size", "date")
        self.tree_trash = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")

        self.tree_trash.heading("restore", text="↻", anchor="center")
        self.tree_trash.heading("file", text="Archivo", anchor="w")
        self.tree_trash.heading("origin", text="Origen", anchor="center")
        self.tree_trash.heading("size", text="Tamaño", anchor="center")
        self.tree_trash.heading("date", text="Fecha de Modificación", anchor="w")

        self.tree_trash.column("restore", width=40, minwidth=40, stretch=False, anchor="center")
        self.tree_trash.column("file", width=520, minwidth=260, stretch=True, anchor="w")
        self.tree_trash.column("origin", width=180, minwidth=120, stretch=True, anchor="center")
        self.tree_trash.column("size", width=140, minwidth=90, stretch=True, anchor="center")
        self.tree_trash.column("date", width=220, minwidth=140, stretch=True, anchor="w")

        self.tree_trash.pack(side="left", fill="both", expand=True)

        sy = ttk.Scrollbar(table, orient="vertical", command=self.tree_trash.yview)
        sy.pack(side="right", fill="y")
        self.tree_trash.configure(yscrollcommand=sy.set)

        self.tree_trash.tag_configure("even", background=ROW_EVEN)
        self.tree_trash.tag_configure("odd", background=ROW_ODD)

        self.tree_trash.bind("<ButtonRelease-1>", self.on_trash_restore_click)
        self._attach_sorting(self.tree_trash, ["file", "origin", "size", "date"])

    def refresh_trash(self):
        assert self.paths is not None
        for iid in self.tree_trash.get_children():
            self.tree_trash.delete(iid)
        self._tree_meta(self.tree_trash).clear()

        entries = []
        for p in self.paths.trash_incoming.rglob("*"):
            if p.is_file():
                entries.append(("INCOMING", p))
        for p in self.paths.trash_processed.rglob("*"):
            if p.is_file():
                entries.append(("PROCESSED", p))

        entries.sort(key=lambda t: t[1].stat().st_mtime if t[1].exists() else 0, reverse=True)
        if not entries:
            self.tree_trash.insert("", tk.END, values=("", "Papelera vacía", "-", "-", "-"))
            self.update_storage_bar()
            return

        meta = self._tree_meta(self.tree_trash)
        idx = 0
        for origin, p in entries:
            st = p.stat()
            iid = str(p)
            tag = "odd" if idx % 2 else "even"
            fmt = file_format(p)
            self.tree_trash.insert("", tk.END, iid=iid,
                                   values=("↻", p.name, origin, human_size(st.st_size), fmt_mtime(st.st_mtime)),
                                   tags=(tag,))
            meta[iid] = {"name": p.name, "size_bytes": st.st_size, "mtime": st.st_mtime, "format": fmt}
            idx += 1

        self.update_storage_bar()

    def on_trash_restore_click(self, event):
        region = self.tree_trash.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree_trash.identify_column(event.x)
        if col != "#1":
            return
        iid = self.tree_trash.identify_row(event.y)
        if not iid:
            return
        vals = self.tree_trash.item(iid, "values")
        if not vals or vals[1] == "Papelera vacía":
            return

        p = Path(iid)
        if not p.exists():
            self.refresh_trash()
            return

        if not messagebox.askyesno("Restaurar", f"¿Restaurar a incoming?\n\n{p.name}"):
            return

        dst = unique_destination(self.paths.incoming / p.name)
        shutil.move(str(p), str(dst))
        self.refresh_trash()
        self.refresh_dashboard()

    def trash_restore_selected(self):
        if not self.paths:
            return
        sel = self.tree_trash.selection()
        if not sel:
            messagebox.showinfo("Info", "No hay archivos seleccionados.")
            return
        if not messagebox.askyesno("Restaurar seleccionados", f"¿Restaurar {len(sel)} archivos a incoming?"):
            return

        restored = 0
        for iid in sel:
            p = Path(iid)
            if p.exists() and p.is_file():
                dst = unique_destination(self.paths.incoming / p.name)
                try:
                    shutil.move(str(p), str(dst))
                    restored += 1
                except Exception:
                    pass

        messagebox.showinfo("OK", f"Restaurados: {restored}")
        self.refresh_trash()
        self.refresh_dashboard()

    def trash_delete_selected(self):
        sel = self.tree_trash.selection()
        if not sel:
            messagebox.showinfo("Info", "No hay archivos seleccionados.")
            return
        if not messagebox.askyesno("Eliminar", f"¿Borrado permanente de {len(sel)} archivos?"):
            return
        deleted = 0
        for iid in sel:
            p = Path(iid)
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                    deleted += 1
                except Exception:
                    pass
        messagebox.showinfo("OK", f"Borrados permanentemente: {deleted}")
        self.refresh_trash()

    def trash_empty(self):
        assert self.paths is not None
        if not messagebox.askyesno("Vaciar", "¿Vaciar papelera (borrado permanente total)?"):
            return
        deleted = 0
        for d in [self.paths.trash_incoming, self.paths.trash_processed]:
            for p in d.rglob("*"):
                if p.is_file():
                    try:
                        p.unlink()
                        deleted += 1
                    except Exception:
                        pass
        messagebox.showinfo("OK", f"Papelera vaciada: {deleted} archivos borrados.")
        self.refresh_trash()

    # ============================================================
    # MUESTREO DE CUENTA DE USUARIO
    # ============================================================
    def show_account(self):
        self._hide_all_views()
        self.view_account.pack(fill="both", expand=True)

    def _build_account_view(self):
        wrap = tk.Frame(self.view_account, bg=BG_APP)
        wrap.pack(fill="both", expand=True, padx=30, pady=30)

        card = Card(wrap, "Cuenta")
        card.pack(fill="x", anchor="n")

        self.lbl_nick = tk.Label(card, text="", bg=BG_CARD, fg=TEXT_PRIMARY, font=("Segoe UI", 10, "bold"))
        self.lbl_nick.pack(anchor="w", padx=16, pady=(6, 2))
        self.lbl_email = tk.Label(card, text="", bg=BG_CARD, fg=TEXT_SECONDARY, font=("Segoe UI", 10))
        self.lbl_email.pack(anchor="w", padx=16, pady=(0, 2))
        self.lbl_contact = tk.Label(card, text="", bg=BG_CARD, fg=TEXT_SECONDARY, font=("Segoe UI", 10))
        self.lbl_contact.pack(anchor="w", padx=16, pady=(0, 10))
        self.lbl_perm = tk.Label(card, text="", bg=BG_CARD, fg=TEXT_SECONDARY, font=("Segoe UI", 10))
        self.lbl_perm.pack(anchor="w", padx=16, pady=(0, 10))

        pw = tk.Frame(card, bg=BG_CARD)
        pw.pack(fill="x", padx=16, pady=(8, 10))
        tk.Label(pw, text="Nueva contraseña", bg=BG_CARD, fg=TEXT_SECONDARY, font=("Segoe UI", 9)).pack(anchor="w")
        self.new_pw = tk.Entry(pw, show="*", bg="#0B1224", fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                               relief="flat", highlightthickness=1, highlightbackground="#1F2A44")
        self.new_pw.pack(fill="x", pady=(4, 0), ipady=6)

        btns = tk.Frame(card, bg=BG_CARD)
        btns.pack(fill="x", padx=16, pady=(0, 16))

        FlatButton(btns, "Cambiar contraseña", BTN_BLUE, "#2563EB", command=self.change_password).pack(side="left")
        FlatButton(btns, "Cerrar sesión", BTN_RED, "#DC2626", command=self.logout).pack(side="right")

        self.view_account.bind("<Visibility>", lambda e: self._refresh_account_labels())

    def _refresh_account_labels(self):
        if not self.current_user:
            return
        self.lbl_nick.config(text=f"Nickname: {self.current_user['nickname']}")
        self.lbl_email.config(text=f"Email: {self.current_user['email']}")
        self.lbl_contact.config(text=f"Contacto: {self.current_user['contact'] or '-'}")
        self.lbl_perm.config(text=f"Permiso: {self.current_user.get('permission','USER')}")

    def change_password(self):
        if not self.current_user:
            return
        np = self.new_pw.get().strip()

        ok, msg = password_ok(np)
        if not ok:
            messagebox.showerror("Cuenta", msg)
            return

        try:
            db_update_password(self.current_user["id"], np)
        except Exception as e:
            messagebox.showerror("Cuenta", f"No se pudo cambiar:\n{e}")
            return
        self.new_pw.delete(0, tk.END)
        messagebox.showinfo("OK", "Contraseña actualizada.")

    def logout(self):
        self.show_start_screen()

    # ============================================================
    # VISTA DE LA LISTA DE USUARIOS (FUNCIONALIDAD ADMIN)
    # ============================================================
    def show_users(self):
        if not self.current_user or not self.current_user.get("is_admin"):
            messagebox.showerror("Permisos", "Solo admin puede acceder.")
            return
        self._hide_all_views()
        self.view_users.pack(fill="both", expand=True)
        self.refresh_users()

    def _build_users_view(self):
        header = tk.Frame(self.view_users, bg=BG_APP)
        header.pack(fill="x", padx=30, pady=20)

        tk.Label(header, text="Usuarios (Admin)", bg=BG_APP, fg=TEXT_PRIMARY,
                 font=("Segoe UI", 14, "bold")).pack(side="left")

        btns = tk.Frame(header, bg=BG_APP)
        btns.pack(side="right")

        FlatButton(btns, "Recargar", BTN_SECONDARY, BTN_SEC_HOVER, text_color=TEXT_PRIMARY,
                   command=self.refresh_users).pack(side="left")

        table = tk.Frame(self.view_users, bg=BG_SURFACE)
        table.pack(fill="both", expand=True, padx=30, pady=(0, 30))

        cols = ("nickname", "email", "contact", "is_admin", "permission", "created_at")
        self.tree_users = ttk.Treeview(table, columns=cols, show="headings", selectmode="browse")

        self.tree_users.heading("nickname", text="Nickname", anchor="w")
        self.tree_users.heading("email", text="Email", anchor="w")
        self.tree_users.heading("contact", text="Contacto", anchor="w")
        self.tree_users.heading("is_admin", text="Admin", anchor="center")
        self.tree_users.heading("permission", text="Permiso", anchor="center")
        self.tree_users.heading("created_at", text="Creado", anchor="w")

        self.tree_users.column("nickname", width=170, minwidth=120, stretch=True, anchor="w")
        self.tree_users.column("email", width=240, minwidth=160, stretch=True, anchor="w")
        self.tree_users.column("contact", width=220, minwidth=140, stretch=True, anchor="w")
        self.tree_users.column("is_admin", width=70, minwidth=70, stretch=False, anchor="center")
        self.tree_users.column("permission", width=140, minwidth=120, stretch=False, anchor="center")
        self.tree_users.column("created_at", width=200, minwidth=160, stretch=True, anchor="w")

        self.tree_users.pack(side="left", fill="both", expand=True)

        sy = ttk.Scrollbar(table, orient="vertical", command=self.tree_users.yview)
        sy.pack(side="right", fill="y")
        self.tree_users.configure(yscrollcommand=sy.set)

        self.tree_users.tag_configure("even", background=ROW_EVEN)
        self.tree_users.tag_configure("odd", background=ROW_ODD)

        self.tree_users.bind("<Button-1>", self.on_users_click_permission)

        self._users_row_map = {}  # iid -> user_id

    def refresh_users(self):
        if not self.current_user or not self.current_user.get("is_admin"):
            return

        for iid in self.tree_users.get_children():
            self.tree_users.delete(iid)

        self._users_row_map.clear()

        rows = db_get_all_users()
        idx = 0
        for r in rows:
            user_id = r["id"]
            tag = "odd" if idx % 2 else "even"
            created = r.get("created_at")

            created_str = str(created)
            created_ts = 0.0
            try:
                created_str = created.strftime("%d/%m/%Y_%H:%M:%S")
                created_ts = created.timestamp()
            except Exception:
                pass

            iid = f"u_{user_id}"
            self.tree_users.insert(
                "", tk.END, iid=iid,
                values=(
                    r.get("nickname", ""),
                    r.get("email", ""),
                    r.get("contact", "") or "",
                    "Sí" if r.get("is_admin") else "No",
                    r.get("permission", "USER"),
                    created_str,
                ),
                tags=(tag,)
            )
            meta = self._tree_meta(self.tree_users)
            meta[iid] = {"mtime": created_ts}
            self._users_row_map[iid] = user_id
            idx += 1

    def on_users_click_permission(self, event):
        if not self.current_user or not self.current_user.get("is_admin"):
            return

        region = self.tree_users.identify("region", event.x, event.y)
        if region != "cell":
            return

        col = self.tree_users.identify_column(event.x)
        if col != "#5":
            return

        row_iid = self.tree_users.identify_row(event.y)
        if not row_iid:
            return

        user_id = self._users_row_map.get(row_iid)
        if not user_id:
            return

        try:
            x, y, w, h = self.tree_users.bbox(row_iid, "permission")
        except Exception:
            return
        if w <= 0:
            return

        current_val = self.tree_users.set(row_iid, "permission")

        if self._perm_combo is not None:
            try:
                self._perm_combo.destroy()
            except Exception:
                pass
            self._perm_combo = None

        self._perm_combo = ttk.Combobox(self.tree_users, values=PERMISSIONS, state="readonly")
        self._perm_combo.set(current_val if current_val in PERMISSIONS else "USER")
        self._perm_combo.place(x=x, y=y, width=w, height=h)

        def commit(_=None):
            new_perm = self._perm_combo.get()
            try:
                db_update_user_permission(user_id, new_perm)
            except Exception as e:
                messagebox.showerror("DB", f"No se pudo actualizar permiso:\n{e}")
            finally:
                try:
                    self._perm_combo.destroy()
                except Exception:
                    pass
                self._perm_combo = None
                self.refresh_users()

        self._perm_combo.bind("<<ComboboxSelected>>", commit)
        self._perm_combo.bind("<FocusOut>", commit)
        self._perm_combo.focus_set()

    # ============================================================
    # GESTIÓN DE FICHEROS
    # ============================================================
    def import_files(self):
        assert self.paths is not None
        paths = filedialog.askopenfilenames(title="Importar documentos")
        if not paths:
            return
        for src in paths:
            srcp = Path(src)
            dst = unique_destination(self.paths.incoming / srcp.name)
            shutil.copy2(srcp, dst)
        self.refresh_dashboard()

    def delete_single_incoming_file(self, filename: str):
        assert self.paths is not None
        target = self.paths.incoming / filename
        if not target.exists():
            return
        if not messagebox.askyesno("Confirmar", f"¿Mover a papelera?\n\n{filename}"):
            return
        safe_move_to_trash(target, self.paths.trash_incoming)
        self.refresh_dashboard()

    def delete_single_processed_file(self, filename: str):
        assert self.paths is not None
        if not self.paths.processed_docs.exists():
            return
        matches = [p for p in self.paths.processed_docs.rglob(filename) if p.is_file()]
        if not matches:
            return
        target = matches[0]
        if not messagebox.askyesno("Confirmar", f"¿Mover a papelera?\n\n{filename}"):
            return
        safe_move_to_trash(target, self.paths.trash_processed)
        self.refresh_dashboard()

    def delete_all_incoming(self):
        assert self.paths is not None
        files = [p for p in self.paths.incoming.iterdir() if p.is_file()]
        if not files:
            return
        if not messagebox.askyesno("Vaciar", f"¿Mover a papelera {len(files)} archivos?"):
            return
        for p in files:
            safe_move_to_trash(p, self.paths.trash_incoming)
        self.refresh_dashboard()

    def open_docs_folder(self):
        assert self.paths is not None
        if not self.paths.processed_docs.exists():
            messagebox.showinfo("Info", "No existe DOCS aún.")
            return
        self._open_folder(self.paths.processed_docs)

    def revert_to_incoming(self):
        assert self.paths is not None
        if not self.paths.processed_docs.exists():
            return
        files = [p for p in self.paths.processed_docs.rglob("*") if p.is_file()]
        if not files:
            messagebox.showinfo("Info", "No hay archivos procesados para revertir.")
            return
        if not messagebox.askyesno("Revertir", f"¿Revertir {len(files)} archivos a incoming?"):
            return
        moved = 0
        for p in files:
            dst = unique_destination(self.paths.incoming / p.name)
            shutil.move(str(p), str(dst))
            moved += 1
        for d in sorted([x for x in self.paths.processed_docs.rglob("*") if x.is_dir()], reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        messagebox.showinfo("OK", f"Revertidos: {moved}")
        self.refresh_dashboard()


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    app = None
    try:
        app = ExcalidocsApp()
        app.mainloop()
    except KeyboardInterrupt:
        if app is not None:
            try:
                app.on_exit()
            except Exception:
                pass