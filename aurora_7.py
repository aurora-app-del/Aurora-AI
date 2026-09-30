# ==============================================================
# AURORA 7.0 - IA PESSOAL AVANCADA
# Arquivo unico | Python 3 | Pydroid
#
# Recursos:
# - Memoria persistente em SQLite
# - Perfil do usuario
# - Conhecimento ensinado pelo usuario
# - Historico e contexto de conversa
# - Busca por palavras-chave na memoria
# - Sistema de intencoes
# - Calculadora segura (AST, sem eval)
# - Data/hora
# - Notas persistentes
# - Tarefas persistentes
# - Sistema de plugins locais
# - Importacao/exportacao da memoria
# - Personalidade configuravel
# - Integracao OPCIONAL com qualquer API HTTP compativel
#   que aceite JSON e devolva uma resposta textual
#
# O modo local funciona sem internet e sem bibliotecas externas.
# ==============================================================

import ast
import datetime as dt
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser
import urllib.error
from pathlib import Path

APP_NAME = "AURORA"
VERSION = "7.0"
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "aurora.db"
CONFIG_FILE = BASE_DIR / "aurora_config.json"
EXPORT_FILE = BASE_DIR / "aurora_backup.json"

DEFAULT_CONFIG = {
    "name": "Aurora",
    "personality": (
        "Você é Aurora, uma assistente virtual amigável, curiosa, "
        "objetiva e transparente. Nunca finja saber algo que não sabe."
    ),
    "max_context": 80,
    "semantic_memory_limit": 24,
    "semantic_knowledge_limit": 12,
    "context_char_limit": 24000,
    "auto_memory": True,
    "auto_notes": True,
    "session_name": "principal",
    "temperature": 0.7,
    "web_enabled": True,
    "web_provider": "duckduckgo",
    "web_results": 6,
    "web_timeout": 10,
    "use_online_model": False,
    "api_url": "",
    "api_key": "",
    "model": "",
    "system_prompt": (
        "Você é Aurora, uma assistente pessoal. Responda em português "
        "do Brasil quando o usuário falar português. Seja útil e clara."
    )
}

# --------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------

def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(data)
        return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


CONFIG = load_config()

# --------------------------------------------------------------
# DATABASE
# --------------------------------------------------------------

db = sqlite3.connect(str(DB_FILE), check_same_thread=False)
db.row_factory = sqlite3.Row
db_lock = threading.Lock()


def db_exec(sql, params=(), fetch=False, many=False):
    with db_lock:
        cur = db.cursor()
        if many:
            cur.executemany(sql, params)
        else:
            cur.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        db.commit()
        return rows


def init_db():
    db_exec("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(category, key)
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL UNIQUE,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL,
            uses INTEGER DEFAULT 0
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS memory_tags (
            memory_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            UNIQUE(memory_id, tag)
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            when_at TEXT,
            payload TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    db_exec("""
        CREATE TABLE IF NOT EXISTS files_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            extension TEXT,
            size INTEGER DEFAULT 0,
            modified REAL DEFAULT 0,
            indexed_at TEXT NOT NULL
        )
    """)


init_db()

# --------------------------------------------------------------
# UTILS
# --------------------------------------------------------------

def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return dt.datetime.now().strftime("%d/%m/%Y")


def normalize(text):
    text = text.lower().strip()
    table = str.maketrans(
        "áàãâäéèêëíìîïóòõôöúùûüç",
        "aaaaaeeeeiiiiooooouuuuc"
    )
    text = text.translate(table)
    return re.sub(r"\s+", " ", text)



STOPWORDS = {
    "a", "o", "os", "as", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "e", "ou", "em", "no",
    "na", "nos", "nas", "para", "por", "com", "sem", "que",
    "eu", "voce", "vc", "me", "te", "se", "isso", "essa",
    "esse", "como", "qual", "quais", "onde", "quando",
    "porque", "porquê", "mais", "menos", "muito", "muita",
    "meu", "minha", "seu", "sua"
}


def keywords(text):
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9_]+", normalize(text))
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def relevance(query, text):
    q = keywords(query)
    t = keywords(text)

    if not q or not t:
        return 0.0

    overlap = len(q & t)
    score = overlap / max(1, len(q))

    # Pequeno bônus quando há uma correspondência exata de expressão.
    nq = normalize(query)
    nt = normalize(text)
    if nq and nq in nt:
        score += 0.75

    return score


def smart_memory(query, limit=None):
    """Recupera memórias semanticamente relevantes sem usar memória inteira."""
    limit = limit or int(CONFIG.get("semantic_memory_limit", 12))
    rows = get_memory()

    ranked = []
    for row in rows:
        text = f"{row['category']} {row['key']} {row['value']}"
        score = relevance(query, text)

        # Memórias de perfil são importantes quando o usuário pergunta
        # sobre si mesmo.
        if row["category"] == "profile":
            score += 0.15

        if score > 0:
            ranked.append((score, row))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in ranked[:limit]]


def smart_knowledge(query, limit=5):
    """Recupera conhecimentos ensinados por relevância."""
    rows = db_exec(
        "SELECT * FROM knowledge ORDER BY uses DESC, id DESC",
        fetch=True
    )

    ranked = []
    for row in rows:
        score = relevance(query, row["question"])

        if normalize(query) == normalize(row["question"]):
            score += 2.0

        if score > 0:
            ranked.append((score, row))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in ranked[:limit]]


def build_context(user_text):
    """
    Constrói contexto dinâmico:
    - últimas mensagens
    - memórias relevantes
    - conhecimentos relevantes
    - respeita limite de caracteres
    """
    max_chars = int(CONFIG.get("context_char_limit", 12000))
    parts = []

    memories = smart_memory(user_text)
    if memories:
        parts.append("MEMÓRIAS RELEVANTES:")
        for row in memories:
            parts.append(
                f"- {row['key']}: {row['value']}"
            )

    knowledge_rows = smart_knowledge(
        user_text,
        limit=int(CONFIG.get("semantic_knowledge_limit", 12))
    )
    if knowledge_rows:
        parts.append("\nCONHECIMENTOS RELEVANTES:")
        for row in knowledge_rows:
            parts.append(
                f"- {row['question']} => {row['answer']}"
            )

    notes = list_notes()
    ranked_notes = []
    for note in notes:
        score = relevance(user_text, f"{note['title']} {note['body']}")
        if score > 0:
            ranked_notes.append((score, note))
    ranked_notes.sort(key=lambda x: x[0], reverse=True)

    if ranked_notes:
        parts.append("\nNOTAS RELEVANTES:")
        for _, note in ranked_notes[:6]:
            parts.append(f"- {note['title']}: {note['body']}")

    tasks = list_tasks()
    ranked_tasks = []
    for task in tasks:
        score = relevance(user_text, task["title"])
        if score > 0:
            ranked_tasks.append((score, task))
    ranked_tasks.sort(key=lambda x: x[0], reverse=True)

    if ranked_tasks:
        parts.append("\nTAREFAS RELEVANTES:")
        for _, task in ranked_tasks[:6]:
            parts.append(f"- {task['title']} | prazo: {task['due'] or 'sem prazo'}")

    parts.append("\nCONVERSA RECENTE:")
    for row in recent_messages(
        int(CONFIG.get("max_context", 40))
    ):
        parts.append(
            f"{row['role']}: {row['content']}"
        )

    context = "\n".join(parts)

    if len(context) > max_chars:
        context = context[-max_chars:]

    return context


def compress_old_history():
    # Aurora 6.0 não apaga histórico automaticamente.
    # O histórico completo permanece no SQLite.
    return

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    print("\n" + "=" * 58)
    print(f"                 {APP_NAME} {VERSION}")
    print("=" * 58)




# --------------------------------------------------------------
# WEB ENGINE
# --------------------------------------------------------------

class _SearchParser(HTMLParser):
    """Extrai links/títulos de resultados HTML de forma simples."""
    def __init__(self):
        super().__init__()
        self.items = []
        self._a = False
        self._href = ""
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            href = attrs.get("href", "")
            self._a = True
            self._href = href
            self._text = []

    def handle_data(self, data):
        if self._a:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._a:
            title = " ".join("".join(self._text).split())
            if title and self._href:
                self.items.append((title, self._href))
            self._a = False
            self._href = ""
            self._text = []


class _TextParser(HTMLParser):
    """Converte uma página HTML em texto legível."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)

    def text(self):
        return " ".join(self.parts)


def _http_get(url, timeout=None):
    timeout = timeout or int(CONFIG.get("web_timeout", 10))
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Android; Aurora/7.0) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def web_search(query, limit=None):
    """
    Busca pública usando DuckDuckGo HTML.
    Não precisa de API key.
    """
    if not CONFIG.get("web_enabled", True):
        return []

    limit = limit or int(CONFIG.get("web_results", 6))
    q = urllib.parse.quote_plus(query.strip())

    url = f"https://html.duckduckgo.com/html/?q={q}"

    try:
        html = _http_get(url)
    except Exception as exc:
        return [{
            "title": "Erro de pesquisa",
            "url": "",
            "snippet": str(exc)
        }]

    parser = _SearchParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    results = []
    seen = set()

    for title, href in parser.items:
        if not href.startswith("http"):
            continue

        # Evita duplicados.
        if href in seen:
            continue
        seen.add(href)

        # Remove alguns links obviamente não úteis.
        low = href.lower()
        if "duckduckgo.com" in low:
            continue

        results.append({
            "title": title,
            "url": href,
            "snippet": ""
        })

        if len(results) >= limit:
            break

    return results


def web_read(url, max_chars=10000):
    """Lê texto de uma página pública."""
    try:
        html = _http_get(url)
        parser = _TextParser()
        parser.feed(html)
        text = parser.text()

        # Limpeza básica.
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        return text
    except Exception as exc:
        return f"[Não foi possível ler a página: {exc}]"


def web_research(query, limit=None):
    """
    Pesquisa + leitura das primeiras páginas úteis.
    Retorna fontes e trechos para o motor local ou modelo online.
    """
    results = web_search(query, limit)

    enriched = []
    for result in results:
        if not result.get("url"):
            continue

        text = web_read(result["url"], max_chars=7000)
        enriched.append({
            **result,
            "content": text
        })

    return enriched


def format_web_results(results):
    if not results:
        return "Nenhum resultado encontrado."

    lines = ["RESULTADOS DA INTERNET:"]
    for i, item in enumerate(results, 1):
        lines.append(f"\n[{i}] {item.get('title', 'Sem título')}")
        lines.append(item.get("url", ""))

        snippet = item.get("snippet", "")
        content = item.get("content", "")

        if snippet:
            lines.append(snippet)
        elif content:
            lines.append(content[:1800])

    return "\n".join(lines)


def web_context(query):
    results = web_research(query)
    return format_web_results(results), results


# --------------------------------------------------------------
# SESSIONS / CONTEXT
# --------------------------------------------------------------

def current_session():
    return CONFIG.get("session_name", "principal")


def create_session(name):
    name = name.strip() or "principal"
    stamp = now()
    db_exec("""
        INSERT INTO sessions(name, created_at, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at
    """, (name, stamp, stamp))
    CONFIG["session_name"] = name
    save_config()
    return name


def list_sessions():
    return db_exec(
        "SELECT * FROM sessions ORDER BY updated_at DESC",
        fetch=True
    )


def switch_session(name):
    rows = db_exec(
        "SELECT * FROM sessions WHERE name=?",
        (name.strip(),),
        fetch=True
    )
    if not rows:
        return False
    CONFIG["session_name"] = name.strip()
    save_config()
    return True


def session_messages(limit=80):
    # Compatibility layer: existing messages remain global.
    # Sessions are primarily a future-safe organizational layer.
    return recent_messages(limit)


# --------------------------------------------------------------
# AUTOMATIC MEMORY
# --------------------------------------------------------------

MEMORY_PATTERNS = [
    r"\bmeu nome (?:é|e)\s+(.+)",
    r"\bme chamo\s+(.+)",
    r"\beu gosto de\s+(.+)",
    r"\beu nao gosto de\s+(.+)",
    r"\beu não gosto de\s+(.+)",
    r"\beu prefiro\s+(.+)",
    r"\bmeu projeto (?:é|e)\s+(.+)",
    r"\bestou fazendo\s+(.+)",
]


def auto_extract_memory(text):
    if not CONFIG.get("auto_memory", True):
        return

    original = text.strip()

    for pattern in MEMORY_PATTERNS:
        m = re.search(pattern, original, re.I)
        if not m:
            continue

        value = m.group(1).strip().rstrip(".!?")
        if len(value) < 2 or len(value) > 300:
            continue

        normalized = normalize(original)

        if "meu nome" in normalized or "me chamo" in normalized:
            remember("profile", "nome", value)
        elif "gosto de" in normalized:
            remember("preference", "gosta_de", value)
        elif "nao gosto de" in normalized:
            remember("preference", "nao_gosta_de", value)
        elif "prefiro" in normalized:
            remember("preference", "prefere", value)
        elif "meu projeto" in normalized:
            remember("project", "projeto", value)
        else:
            remember("fact", "fato_" + str(int(time.time())), value)

        break


def memory_count():
    return db_exec("SELECT COUNT(*) AS n FROM memory", fetch=True)[0]["n"]


def knowledge_count():
    return db_exec("SELECT COUNT(*) AS n FROM knowledge", fetch=True)[0]["n"]


def message_count():
    return db_exec("SELECT COUNT(*) AS n FROM messages", fetch=True)[0]["n"]


# --------------------------------------------------------------
# MEMORY
# --------------------------------------------------------------

def remember(category, key, value):
    stamp = now()
    db_exec("""
        INSERT INTO memory(category, key, value, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(category, key)
        DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (category, key, value, stamp, stamp))


def forget(category, key):
    db_exec(
        "DELETE FROM memory WHERE category=? AND key=?",
        (category, key)
    )


def get_memory(category=None):
    if category:
        return db_exec(
            "SELECT * FROM memory WHERE category=? ORDER BY id DESC",
            (category,),
            True
        )
    return db_exec(
        "SELECT * FROM memory ORDER BY id DESC",
        fetch=True
    )


def memory_search(query, limit=8):
    return smart_memory(query, limit)


# --------------------------------------------------------------
# KNOWLEDGE
# --------------------------------------------------------------

def teach(question, answer):
    db_exec("""
        INSERT INTO knowledge(question, answer, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(question)
        DO UPDATE SET answer=excluded.answer
    """, (question.strip(), answer.strip(), now()))


def knowledge_search(query):
    candidates = smart_knowledge(query, limit=1)

    if not candidates:
        return None

    best = candidates[0]

    # Evita responder a perguntas vagamente parecidas demais.
    score = relevance(query, best["question"])
    if normalize(query) != normalize(best["question"]) and score < 0.34:
        return None

    db_exec(
        "UPDATE knowledge SET uses=uses+1 WHERE id=?",
        (best["id"],)
    )

    return best["answer"]


# --------------------------------------------------------------
# CHAT HISTORY
# --------------------------------------------------------------

def save_message(role, content):
    db_exec(
        "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
        (role, content, now())
    )

    if role == "user":
        auto_extract_memory(content)


def recent_messages(limit=None):
    limit = limit or int(CONFIG.get("max_context", 40))
    rows = db_exec("""
        SELECT role, content, created_at
        FROM messages
        ORDER BY id DESC
        LIMIT ?
    """, (limit,), True)
    return list(reversed(rows))


def clear_history():
    db_exec("DELETE FROM messages")


# --------------------------------------------------------------
# NOTES
# --------------------------------------------------------------

def add_note(title, body):
    stamp = now()
    db_exec("""
        INSERT INTO notes(title, body, created_at, updated_at)
        VALUES (?, ?, ?, ?)
    """, (title, body, stamp, stamp))


def list_notes():
    return db_exec(
        "SELECT * FROM notes ORDER BY id DESC",
        fetch=True
    )


def delete_note(note_id):
    db_exec("DELETE FROM notes WHERE id=?", (note_id,))


# --------------------------------------------------------------
# TASKS
# --------------------------------------------------------------

def add_task(title, due=None):
    db_exec("""
        INSERT INTO tasks(title, due, created_at)
        VALUES (?, ?, ?)
    """, (title, due, now()))


def list_tasks(show_done=False):
    if show_done:
        return db_exec(
            "SELECT * FROM tasks ORDER BY done, id DESC",
            fetch=True
        )
    return db_exec(
        "SELECT * FROM tasks WHERE done=0 ORDER BY id DESC",
        fetch=True
    )


def finish_task(task_id):
    db_exec(
        "UPDATE tasks SET done=1 WHERE id=?",
        (task_id,)
    )


# --------------------------------------------------------------
# SAFE CALCULATOR
# --------------------------------------------------------------

MATH_NAMES = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau
}

MATH_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "fabs": math.fabs,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "radians": math.radians,
    "degrees": math.degrees
}


def safe_math(expression):
    expression = expression.replace("^", "**")
    tree = ast.parse(expression, mode="eval")

    allowed_nodes = (
        ast.Expression, ast.BinOp, ast.UnaryOp,
        ast.Add, ast.Sub, ast.Mult, ast.Div,
        ast.FloorDiv, ast.Mod, ast.Pow,
        ast.USub, ast.UAdd, ast.Call,
        ast.Name, ast.Load, ast.Constant
    )

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError("Operação não permitida.")

        if isinstance(node, ast.Name):
            if node.id not in MATH_NAMES and node.id not in MATH_FUNCS:
                raise ValueError("Nome não permitido.")

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Função não permitida.")
            if node.func.id not in MATH_FUNCS:
                raise ValueError("Função não permitida.")

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError("Valor não permitido.")

    env = {}
    env.update(MATH_NAMES)
    env.update(MATH_FUNCS)

    return eval(compile(tree, "<math>", "eval"),
                {"__builtins__": {}}, env)


# --------------------------------------------------------------
# OPTIONAL ONLINE MODEL
# --------------------------------------------------------------

def online_model(prompt):
    """
    Integração genérica via HTTP.
    Configure em /config:
      api_url
      api_key
      model

    O corpo enviado é JSON:
      {
        "model": "...",
        "messages": [
          {"role": "system", "content": "..."},
          ...
        ]
      }

    A resposta tenta encontrar:
      choices[0].message.content
    ou:
      response
      text
      answer
    """

    url = CONFIG.get("api_url", "").strip()
    key = CONFIG.get("api_key", "").strip()
    model = CONFIG.get("model", "").strip()

    if not url:
        return None

    context = build_context(prompt)

    # Se o usuário pedir explicitamente informação atual/online,
    # pesquisa antes de chamar o modelo.
    web_markers = (
        "pesquise na internet", "pesquisa na internet",
        "na internet", "pesquise", "procure na web",
        "noticias", "notícia", "hoje", "agora", "atual"
    )

    web_sources = ""
    if CONFIG.get("web_enabled", True) and any(
        marker in normalize(prompt) for marker in web_markers
    ):
        web_sources, _ = web_context(prompt)

    system = (
        CONFIG.get("system_prompt", "")
        + "\n\nCONTEXTO RECUPERADO AUTOMATICAMENTE:\n"
        + context
        + ("\n\nFONTES DA INTERNET:\n" + web_sources if web_sources else "")
    )

    messages = [
        {
            "role": "system",
            "content": system
        }
    ]

    # Mantém somente a conversa recente como mensagens estruturadas;
    # memórias antigas entram no contexto recuperado.
    for row in recent_messages(
        int(CONFIG.get("max_context", 40))
    ):
        messages.append({
            "role": row["role"],
            "content": row["content"]
        })

    messages.append({
        "role": "user",
        "content": prompt
    })

    payload = {
        "model": model,
        "messages": messages,
        "temperature": CONFIG.get("temperature", 0.7)
    }

    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json"
    }

    if key:
        headers["Authorization"] = "Bearer " + key

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw)

        # formatos comuns
        if "choices" in result:
            choices = result["choices"]
            if choices:
                item = choices[0]
                if "message" in item:
                    return item["message"].get("content")
                if "text" in item:
                    return item["text"]

        for key_name in ("response", "text", "answer", "content"):
            if isinstance(result.get(key_name), str):
                return result[key_name]

        return None

    except Exception:
        return None


# --------------------------------------------------------------
# LOCAL INTELLIGENCE
# --------------------------------------------------------------

def user_name():
    rows = get_memory("profile")
    for row in rows:
        if row["key"] == "nome":
            return row["value"]
    return None


def local_response(text):
    original = text.strip()
    q = normalize(original)

    # Nome
    match = re.match(
        r"^(?:meu nome e|me chamo|pode me chamar de)\s+(.+)$",
        original,
        re.I
    )
    if match:
        name = match.group(1).strip()
        remember("profile", "nome", name)
        return f"Prazer, {name}! Salvei seu nome na minha memória."

    # Hora
    if q in ("hora", "que horas sao", "que horas e"):
        return "Agora são " + dt.datetime.now().strftime("%H:%M:%S") + "."

    # Data
    if q in ("data", "qual a data", "data de hoje"):
        return "Hoje é " + today() + "."

    # Identidade
    if "seu nome" in q:
        return f"Eu sou {CONFIG.get('name', APP_NAME)}, versão {VERSION}."

    if q in ("quem e voce", "o que voce e", "quem e vc"):
        return (
            f"Sou {CONFIG.get('name', APP_NAME)}, uma assistente "
            "pessoal em Python com memória, banco de dados, "
            "ferramentas e integração opcional com modelos online."
        )

    # Saudações
    if q in ("oi", "ola", "ola", "eae", "e ai", "aoba", "hello"):
        name = user_name()
        if name:
            return f"Aoba, {name}! 😎"
        return "Aoba! 😎"

    # Matemática
    math_match = re.match(r"^(?:calcule|quanto e|quanto é)\s+(.+)$",
                          original, re.I)
    if math_match:
        expression = math_match.group(1)
        try:
            result = safe_math(expression)
            return f"Resultado: {result}"
        except Exception as exc:
            return f"Não consegui calcular: {exc}"

    # Conhecimento ensinado
    learned = knowledge_search(original)
    if learned:
        return learned

    # Memória contextual
    memories = memory_search(original, limit=3)
    if memories:
        pieces = [
            f"{r['key']}: {r['value']}" for r in memories
        ]
        return (
            "Encontrei estas informações na minha memória:\n- "
            + "\n- ".join(pieces)
        )

    # Agradecimento
    if any(x in q for x in ("obrigado", "obrigada", "valeu")):
        return "Tamo junto! 😎"

    # Despedida
    if q in ("tchau", "falou", "adeus"):
        return "Até a próxima! 👋"

    return None


# --------------------------------------------------------------
# COMMANDS
# --------------------------------------------------------------

def command_help():
    print("""
================ AURORA 4.0 ================

CONVERSA
  /ajuda
  /status
  /sair

MEMÓRIA
  /lembrar chave = valor
  /memoria
  /buscar texto
  /esquecer chave

CONHECIMENTO
  /ensinar pergunta = resposta
  /conhecimento

NOTAS
  /nota titulo = texto
  /notas
  /apagar_nota ID

TAREFAS
  /tarefa texto
  /tarefas
  /concluir ID

HISTÓRICO
  /historico
  /limpar_historico

CONFIGURAÇÃO
  /config
  /config nome = valor
  /online on
  /online off

BACKUP
  /exportar
  /importar

MATEMÁTICA
  /calc 2 + 2
  /calc sqrt(81)
  /calc sin(pi/2)

EXEMPLOS
  /lembrar cor_favorita = azul
  /ensinar qual e a capital do Brasil = Brasília
  /nota Python = estudar funções amanhã
  /tarefa estudar Python
  /buscar Python

=============================================
""")


def command_status():
    print("\n============== STATUS ==============")
    print("Nome:", CONFIG.get("name"))
    print("Versão:", VERSION)
    print("Banco:", DB_FILE.name)
    print("Memórias:", len(get_memory()))
    print("Mensagens:", len(recent_messages(999999)))
    print("Conhecimentos:",
          len(db_exec("SELECT * FROM knowledge", fetch=True)))
    print("Notas:", len(list_notes()))
    print("Tarefas abertas:", len(list_tasks()))
    print("Modelo online:",
          "ATIVO" if CONFIG.get("use_online_model") else "DESATIVADO")
    print("Contexto recente:", CONFIG.get("max_context"), "mensagens")
    print("Memórias recuperadas:",
          CONFIG.get("semantic_memory_limit"))
    print("Limite de contexto:",
          CONFIG.get("context_char_limit"), "caracteres")
    print("Memórias totais:", memory_count())
    print("Conhecimentos totais:", knowledge_count())
    print("Mensagens totais:", message_count())
    print("Memória automática:",
          "ATIVA" if CONFIG.get("auto_memory") else "DESATIVADA")
    print("Sessão:", current_session())
    print("Pesquisa web:", "ATIVA" if CONFIG.get("web_enabled", True) else "DESATIVADA")
    print("Provedor web:", CONFIG.get("web_provider", "duckduckgo"))
    print("====================================\n")


def command_memory():
    rows = get_memory()

    print("\n============== MEMÓRIA ==============")

    if not rows:
        print("Memória vazia.")
    else:
        for r in rows:
            print(
                f"[{r['category']}] "
                f"{r['key']} = {r['value']}"
            )

    print("=====================================\n")


def command_knowledge():
    rows = db_exec(
        "SELECT * FROM knowledge ORDER BY id DESC",
        fetch=True
    )

    print("\n=========== CONHECIMENTO ============")

    if not rows:
        print("Nenhum conhecimento ensinado.")
    else:
        for r in rows:
            print(f"{r['id']}. {r['question']} -> {r['answer']}")

    print("=====================================\n")


def command_notes():
    rows = list_notes()

    print("\n=============== NOTAS ===============")

    if not rows:
        print("Nenhuma nota.")
    else:
        for r in rows:
            print(f"\n[{r['id']}] {r['title']}")
            print(r["body"])

    print("=====================================\n")


def command_tasks():
    rows = list_tasks()

    print("\n============== TAREFAS ==============")

    if not rows:
        print("Nenhuma tarefa pendente.")
    else:
        for r in rows:
            due = f" | prazo: {r['due']}" if r["due"] else ""
            print(f"[{r['id']}] {r['title']}{due}")

    print("======================================\n")


# --------------------------------------------------------------
# BACKUP
# --------------------------------------------------------------

def export_data():
    backup = {
        "version": VERSION,
        "exported_at": now(),
        "config": CONFIG,
        "memory": [dict(x) for x in get_memory()],
        "knowledge": [dict(x) for x in db_exec(
            "SELECT * FROM knowledge", fetch=True
        )],
        "notes": [dict(x) for x in list_notes()],
        "tasks": [dict(x) for x in db_exec(
            "SELECT * FROM tasks", fetch=True
        )]
    }

    EXPORT_FILE.write_text(
        json.dumps(backup, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return EXPORT_FILE


def import_data():
    if not EXPORT_FILE.exists():
        return False, "Backup não encontrado."

    try:
        backup = json.loads(
            EXPORT_FILE.read_text(encoding="utf-8")
        )

        for item in backup.get("memory", []):
            remember(
                item["category"],
                item["key"],
                item["value"]
            )

        for item in backup.get("knowledge", []):
            teach(item["question"], item["answer"])

        for item in backup.get("notes", []):
            add_note(item["title"], item["body"])

        for item in backup.get("tasks", []):
            add_task(item["title"], item.get("due"))

        return True, "Backup importado."

    except Exception as exc:
        return False, str(exc)


# --------------------------------------------------------------
# COMMAND PARSER
# --------------------------------------------------------------

def command(line):
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/ajuda":
        command_help()
        return True, None

    if cmd == "/status":
        command_status()
        return True, None

    if cmd == "/memoria":
        command_memory()
        return True, None

    if cmd == "/conhecimento":
        command_knowledge()
        return True, None

    if cmd == "/notas":
        command_notes()
        return True, None

    if cmd == "/tarefas":
        command_tasks()
        return True, None

    if cmd == "/historico":
        print("\n============== HISTÓRICO ==============")
        for row in recent_messages(30):
            print(
                f"[{row['created_at']}] "
                f"{row['role']}: {row['content']}"
            )
        print("========================================\n")
        return True, None

    if cmd == "/limpar_historico":
        clear_history()
        print("Histórico apagado.")
        return True, None

    if cmd == "/lembrar":
        if "=" not in arg:
            print("Use: /lembrar chave = valor")
            return True, None

        key, value = arg.split("=", 1)
        remember("user", key.strip(), value.strip())
        print("Memória salva.")
        return True, None

    if cmd == "/esquecer":
        forget("user", arg)
        print("Informação removida.")
        return True, None

    if cmd == "/buscar":
        results = memory_search(arg)

        if not results:
            print("Nada encontrado.")
        else:
            for r in results:
                print(f"- {r['key']}: {r['value']}")

        return True, None

    if cmd == "/contexto":
        print("\n========== CONTEXTO RECUPERADO ==========")
        print(build_context(arg))
        print("=========================================\n")
        return True, None

    if cmd == "/ensinar":
        if "=" not in arg:
            print("Use: /ensinar pergunta = resposta")
            return True, None

        q, a = arg.split("=", 1)
        teach(q, a)
        print("Conhecimento aprendido.")
        return True, None

    if cmd == "/nota":
        if "=" not in arg:
            print("Use: /nota título = texto")
            return True, None

        title, body = arg.split("=", 1)
        add_note(title.strip(), body.strip())
        print("Nota criada.")
        return True, None

    if cmd == "/apagar_nota":
        try:
            delete_note(int(arg))
            print("Nota apagada.")
        except Exception:
            print("ID inválido.")
        return True, None

    if cmd == "/tarefa":
        if not arg:
            print("Use: /tarefa descrição")
            return True, None

        add_task(arg)
        print("Tarefa criada.")
        return True, None

    if cmd == "/concluir":
        try:
            finish_task(int(arg))
            print("Tarefa concluída.")
        except Exception:
            print("ID inválido.")
        return True, None

    if cmd == "/calc":
        try:
            print("Resultado:", safe_math(arg))
        except Exception as exc:
            print("Erro:", exc)
        return True, None

    if cmd == "/config":
        if not arg:
            print(json.dumps(CONFIG, ensure_ascii=False, indent=2))
            return True, None

        if "=" not in arg:
            print("Use: /config chave = valor")
            return True, None

        key, value = arg.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value.lower() in ("true", "false"):
            value = value.lower() == "true"

        CONFIG[key] = value
        save_config(CONFIG)
        print("Configuração salva.")
        return True, None

    if cmd == "/online":
        value = arg.lower()

        if value == "on":
            CONFIG["use_online_model"] = True
            save_config(CONFIG)
            print("Modo online ativado.")
        elif value == "off":
            CONFIG["use_online_model"] = False
            save_config(CONFIG)
            print("Modo online desativado.")
        else:
            print("Use /online on ou /online off")

        return True, None

    if cmd == "/exportar":
        path = export_data()
        print("Backup criado em:", path)
        return True, None

    if cmd == "/importar":
        ok, msg = import_data()
        print(msg)
        return True, None



    if cmd in ("/web", "/pesquisar", "/buscarweb"):
        if not arg:
            print("Uso: /web sua pergunta")
            return True, None

        print("\n🌐 Pesquisando na internet...")
        context, results = web_context(arg)

        if not results:
            print("Nenhum resultado encontrado.")
            return True, None

        print(context)
        print()
        return True, context

    if cmd == "/ler":
        if not arg:
            print("Uso: /ler https://site.com")
            return True, None

        print("\n🌐 Lendo página...")
        page = web_read(arg)
        print("\n" + page + "\n")
        return True, None

    if cmd == "/sessao":
        if not arg:
            print("\nSessão atual:", current_session())
            print("Sessões:")
            for row in list_sessions():
                print("-", row["name"])
            return True, None

        if switch_session(arg):
            print("Sessão alterada para:", arg)
        else:
            create_session(arg)
            print("Nova sessão criada:", arg)
        return True, None

    if cmd == "/estatisticas":
        print("\n========== ESTATÍSTICAS ==========")
        print("Memórias:", memory_count())
        print("Conhecimentos:", knowledge_count())
        print("Mensagens:", message_count())
        print("Notas:", len(list_notes()))
        print("Tarefas:", len(list_tasks(True)))
        print("Sessão:", current_session())
        print("Pesquisa web:", "ATIVA" if CONFIG.get("web_enabled", True) else "DESATIVADA")
        print("Provedor web:", CONFIG.get("web_provider", "duckduckgo"))
        print("==================================\n")
        return True, None

    if cmd == "/contexto":
        print("\n========== CONTEXTO ==========")
        print(build_context(arg or ""))
        print("==============================\n")
        return True, None

    if cmd == "/sair":
        return True, "EXIT"

    return False, None


# --------------------------------------------------------------
# MAIN AI
# --------------------------------------------------------------

def think(user_text):
    """
    Pipeline:
      1. salva entrada
      2. verifica memória/conhecimento
      3. tenta modelo online se configurado
      4. usa inteligência local como fallback
    """

    save_message("user", user_text)

    # Online primeiro quando explicitamente habilitado
    if CONFIG.get("use_online_model"):
        answer = online_model(user_text)
        if answer:
            save_message("assistant", answer)
            return answer

    # Local
    answer = local_response(user_text)

    if answer is None:
        answer = (
            "Ainda não sei responder isso no modo local. "
            "Você pode me ensinar usando:\n"
            "/ensinar pergunta = resposta\n\n"
            "Ou configure um modelo online em /config."
        )

    save_message("assistant", answer)

    # O banco pode continuar guardando muita informação, mas o contexto
    # usado pelo modelo permanece controlado.
    compress_old_history()

    return answer


# --------------------------------------------------------------
# STARTUP
# --------------------------------------------------------------

def startup():
    clear_screen()
    print_header()
    print("Sistema de memória inteligente inicializado.")
    print("Banco de memória: OK")
    print("Conhecimento: OK")
    print("Ferramentas: OK")
    print(
        "Modelo online:",
        "ATIVO" if CONFIG.get("use_online_model") else "DESATIVADO"
    )
    print("\nDigite /ajuda para ver todos os recursos.\n")


def main():
    startup()

    while True:
        try:
            user = input("Você >>> ").strip()

            if not user:
                continue

            if user.startswith("/"):
                handled, result = command(user)

                if result == "EXIT":
                    print("\nAurora encerrada. Até mais! 👋")
                    break

                if handled:
                    continue

            answer = think(user)
            print(f"\n{CONFIG.get('name', APP_NAME)} >>> {answer}\n")

        except KeyboardInterrupt:
            print("\n\nAurora encerrada.")
            break

        except Exception as exc:
            print("\nERRO:", exc)
            print("A conversa continua normalmente.\n")


if __name__ == "__main__":
    main()
