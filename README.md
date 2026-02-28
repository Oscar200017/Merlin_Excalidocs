# Merlin Excalidocs (Proyecto de Merlín Software)

Aplicación de escritorio (Tkinter) para **importar, ordenar, auditar y gestionar documentos** por usuario, con soporte de:
- **Registro/Login** (email o nickname)
- **Roles/permisos** gestionables por admin
- **Ordenación de documentos por Formato/Año/Mes**
- **Logs (Audit Trail)** con columna de categoría clickable (abre carpeta)
- **Papelera** con restauración y borrado
- **Almacenamiento**: barra de uso por usuario (procesados + papelera)
- Persistencia en **PostgreSQL** + auditoría en **JSON local** (solo admin)

---

## Estructura del proyecto (resumen)
merlin-docs/
├─ backend/
├─ dist/
│ └─ Excalidocs
├─ frontend/
│ └─ gui_ingestor.py
├─ storage/
│ ├─ admin/
│ │ └─ users_admin.json
│ └─ users/
│ ├─ users.json
│ └─ <nickname>/
│ ├─ incoming/
│ │ └─ _trash/
│ └─ processed/
│ ├─ manifest.csv
│ └─ DOCS/
│ ├─ PDF/
│ │ └─ 2026/
│ │ └─ 02/
│ └─ ...

---

## Login / Registro / Roles

### Login
- El login admite **EMAIL o NICKNAME** (uno u otro).
- Contraseña mínima: **6 caracteres**.

### Admin por defecto
Siempre se fuerza/crea un usuario admin:
- **Usuario:** `admin`
- **Contraseña:** `administrador`

> Si ya existía en DB, se asegura `is_admin=TRUE` y `permission='ADMIN'`.

### Roles disponibles
- `USER`
- `POWER`
- `EXECUTOR`
- `ADMIN`

Importante: al cambiar un usuario de `ADMIN` a otro rol, **pierde** `is_admin` (downgrade real).

---

## Ordenación de documentos

Los documentos se ordenan desde `incoming/` hacia:
storage/users/<nickname>/processed/DOCS/<FORMATO>/<AÑO>/<MES>/

---

## Logs (Audit Trail)

- Se guardan en:
storage/users/<nickname>/processed/manifest.csv

- Columnas:
- `original_filename`
- `stored_path`
- `sha256`
- `size_bytes`
- `ext`
- `category`
- `year`
- `last_write_time`

### Categoría clickable
En la pantalla de Logs, la columna **Categoría Asignada** es clickable:
- Abre la carpeta real donde está el documento (`.../<AÑO>/<MES>/`).
- Si no existe, muestra un mensaje informativo.

---

## Papelera

- Cada usuario tiene papelera separada:
- `incoming/_trash/`
- `processed/DOCS/_trash/`

Acciones:
- Restaurar (uno a uno con ↻ o seleccionados)
- Eliminar seleccionados (borrado permanente)
- Vaciar papelera

La restauración devuelve a:
storage/users/<nickname>/incoming/

---

## Barra de almacenamiento

En la sidebar aparece un medidor de:
- Tamaño total de `processed/DOCS/` **+** tamaño total de la papelera del usuario (`incoming/_trash` y `processed/DOCS/_trash`)

Máximo configurado: **100 GB**.

---

## Panel de Usuarios (solo Admin)

En la sidebar del admin aparece **Usuarios**:
- Lista de usuarios desde PostgreSQL con:
  - nickname, email, contacto, admin, permiso, fecha creación
- La columna **Permiso** es editable (dropdown por fila)
- Cambio de permiso impacta en DB:
  - `ADMIN` ⇒ `is_admin=TRUE`
  - no-ADMIN ⇒ `is_admin=FALSE`

---

## Cómo ejecutar (modo desarrollo)

### 1) Crear venv e instalar dependencias
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecutar GUI
```bash
python .\frontend\gui_ingestor.py
```