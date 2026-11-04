# ==============================================================
# AURORA 8.0 - Assistente pessoal com IA real (Claude) para Android
#
# - Conversa de verdade com o Claude pela API da Anthropic
# - Memoria, notas e tarefas salvas no celular (SQLite)
# - Tudo configuravel dentro do app (chave, modelo, personalidade)
# - Arquivo unico, pronto para o Buildozer (main.py)
# ==============================================================

import datetime as dt
import json
import os
import sqlite3
import threading

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

DEFAULT_CONFIG = {
    "api_key": "",
    "model": "claude-sonnet-5-5",
    "max_tokens": 1024,
    "max_history": 24,
    "personality": (
        "Você é Aurora, uma assistente pessoal em português do Brasil. "
        "Seja clara, objetiva e simpática. Se não souber algo, diga que "
        "não sabe. Você não tem acesso à internet nem ao celular do "
        "usuário: nunca finja ter feito uma ação que não fez."
    ),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL, content TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL, done INTEGER DEFAULT 0, ts TEXT NOT NULL);
"""

HELP = (
    "Comandos:\n"
    "/lembrar texto  - guarda um fato sobre você\n"
    "/memoria  - lista o que eu sei sobre você\n"
    "/esquecer N  - apaga a memória de número N\n"
    "/nota texto  - salva uma nota\n"
    "/notas  - lista as notas\n"
    "/tarefa texto  - cria uma tarefa\n"
    "/tarefas  - lista as tarefas abertas\n"
    "/feito N  - conclui a tarefa N\n"
    "/limpar  - apaga o histórico da conversa\n\n"
    "Qualquer outra mensagem vai direto para a IA."
)


class AuroraError(Exception):
    """Erro com mensagem pronta para mostrar ao usuario."""


# --------------------------------------------------------------
# ARMAZENAMENTO
# --------------------------------------------------------------
class Store:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.db_path = os.path.join(folder, "aurora.db")
        self.cfg_path = os.path.join(folder, "config.json")
        self.lock = threading.Lock()
        self.cfg = dict(DEFAULT_CONFIG)
        try:
            with open(self.cfg_path, encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except Exception:
            pass
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def save_cfg(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)

    def q(self, sql, params=(), fetch=False):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sql, params)
                rows = cur.fetchall() if fetch else None
                conn.commit()
                return rows
            finally:
                conn.close()

    @staticmethod
    def _now():
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # mensagens
    def add_msg(self, role, content):
        self.q("INSERT INTO messages(role,content,ts) VALUES(?,?,?)",
               (role, content, self._now()))

    def history(self, n):
        rows = self.q("SELECT role,content FROM messages "
                      "ORDER BY id DESC LIMIT ?", (n,), True)
        return list(reversed(rows))

    def clear_history(self):
        self.q("DELETE FROM messages")

    # memoria / notas / tarefas
    def add(self, table, text):
        self.q(f"INSERT INTO {table}(text,ts) VALUES(?,?)",
               (text, self._now()))

    def list(self, table, only_open=False):
        extra = " WHERE done=0" if only_open else ""
        return self.q(f"SELECT * FROM {table}{extra} ORDER BY id", (), True)

    def delete(self, table, item_id):
        self.q(f"DELETE FROM {table} WHERE id=?", (item_id,))

    def finish_task(self, item_id):
        self.q("UPDATE tasks SET done=1 WHERE id=?", (item_id,))


# --------------------------------------------------------------
# COMANDOS LOCAIS
# --------------------------------------------------------------
def _fmt(rows, empty):
    if not rows:
        return empty
    return "\n".join(f"{r['id']}. {r['text']}" for r in rows)


def handle_command(store, text):
    """Retorna a resposta do comando, ou None se nao for comando."""
    if not text.startswith("/"):
        return None
    cmd, _, arg = text[1:].partition(" ")
    cmd, arg = cmd.lower().strip(), arg.strip()

    def num():
        return int(arg) if arg.isdigit() else None

    if cmd in ("ajuda", "help"):
        return HELP
    if cmd == "lembrar":
        if not arg:
            return "Use: /lembrar o que devo guardar"
        store.add("memory", arg)
        return "Anotado. Vou lembrar disso."
    if cmd == "memoria":
        return _fmt(store.list("memory"), "Ainda não sei nada sobre você.")
    if cmd == "esquecer":
        n = num()
        if n is None:
            return "Use: /esquecer número (veja em /memoria)"
        store.delete("memory", n)
        return "Esquecido."
    if cmd == "nota":
        if not arg:
            return "Use: /nota texto da nota"
        store.add("notes", arg)
        return "Nota salva."
    if cmd == "notas":
        return _fmt(store.list("notes"), "Nenhuma nota.")
    if cmd == "tarefa":
        if not arg:
            return "Use: /tarefa o que precisa fazer"
        store.add("tasks", arg)
        return "Tarefa criada."
    if cmd == "tarefas":
        return _fmt(store.list("tasks", True), "Nenhuma tarefa aberta.")
    if cmd == "feito":
        n = num()
        if n is None:
            return "Use: /feito número (veja em /tarefas)"
        store.finish_task(n)
        return "Tarefa concluída."
    if cmd == "limpar":
        store.clear_history()
        return "Histórico apagado. Memórias, notas e tarefas continuam salvas."
    return "Comando desconhecido. Digite /ajuda."


# --------------------------------------------------------------
# IA (CLAUDE)
# --------------------------------------------------------------
def build_system(store):
    now = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    parts = [store.cfg["personality"], f"Data e hora atuais: {now}."]
    mems = store.list("memory")
    if mems:
        parts.append("O que você sabe sobre o usuário:\n" +
                     "\n".join(f"- {m['text']}" for m in mems))
    tasks = store.list("tasks", True)
    if tasks:
        parts.append("Tarefas abertas do usuário:\n" +
                     "\n".join(f"- {t['text']}" for t in tasks))
    notes = store.list("notes")[-10:]
    if notes:
        parts.append("Notas recentes do usuário:\n" +
                     "\n".join(f"- {n['text']}" for n in notes))
    return "\n\n".join(parts)


def clean_history(rows):
    """A API exige papeis alternados, comecando por 'user'."""
    out = []
    for r in rows:
        text = (r["content"] or "").strip()
        if not text:
            continue
        if out and out[-1]["role"] == r["role"]:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": r["role"], "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def ask_claude(store):
    cfg = store.cfg
    key = cfg["api_key"].strip()
    if not key:
        raise AuroraError(
            "Falta a chave da API. Toque em Config e cole a sua chave "
            "(console.anthropic.com).")
    msgs = clean_history(store.history(int(cfg["max_history"])))
    if not msgs:
        raise AuroraError("Nada para responder.")
    body = {
        "model": cfg["model"].strip(),
        "max_tokens": int(cfg["max_tokens"]),
        "system": build_system(store),
        "messages": msgs,
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    r = requests.post(API_URL, headers=headers, json=body, timeout=90)
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            detail = ""
        if r.status_code == 401:
            raise AuroraError("Chave da API inválida. Confira em Config.")
        if r.status_code == 404:
            raise AuroraError(
                f"Modelo não encontrado ({cfg['model']}). Confira em Config.")
        if r.status_code == 429:
            raise AuroraError("Muitas mensagens seguidas. Espere um pouco.")
        raise AuroraError(f"Erro {r.status_code}: {detail or 'tente de novo.'}")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text").strip()
    if not text:
        raise AuroraError("A IA não devolveu texto. Tente de novo.")
    return text


# ---------------------------- UI ------------------------------
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

BG = (0.07, 0.08, 0.11, 1)
MINE = (0.20, 0.45, 0.85, 1)
HERS = (0.17, 0.19, 0.24, 1)


class Bubble(Label):
    def __init__(self, text, mine, **kw):
        super().__init__(
            text=text, size_hint=(0.86, None),
            pos_hint={"right": 1} if mine else {"x": 0},
            halign="left", valign="top", color=(1, 1, 1, 1), **kw)
        with self.canvas.before:
            Color(*(MINE if mine else HERS))
            self._rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(width=self._wrap, texture_size=self._fit,
                  pos=self._draw, size=self._draw)

    def _wrap(self, *a):
        self.text_size = (self.width - dp(24), None)

    def _fit(self, *a):
        self.height = self.texture_size[1] + dp(20)

    def _draw(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size


class AuroraApp(App):
    title = "Aurora"

    def build(self):
        Window.clearcolor = BG
        Window.softinput_mode = "below_target"
        self.store = Store(self.user_data_dir)
        self.busy = False
        self.thinking = None

        root = BoxLayout(orientation="vertical", spacing=dp(6),
                         padding=dp(8))
        top = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        top.add_widget(Label(text="Aurora", font_size=dp(22), bold=True,
                             halign="left", valign="middle"))
        cfg_btn = Button(text="Config", size_hint_x=None, width=dp(90))
        cfg_btn.bind(on_release=self.open_config)
        top.add_widget(cfg_btn)
        root.add_widget(top)

        self.scroll = ScrollView(do_scroll_x=False)
        self.chat = BoxLayout(orientation="vertical", size_hint_y=None,
                              spacing=dp(8), padding=(dp(2), dp(4)))
        self.chat.bind(minimum_height=self.chat.setter("height"))
        self.scroll.add_widget(self.chat)
        root.add_widget(self.scroll)

        bottom = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.input = TextInput(hint_text="Escreva uma mensagem...",
                               multiline=False, write_tab=False,
                               font_size=dp(16))
        self.input.bind(on_text_validate=self.send)
        send_btn = Button(text="Enviar", size_hint_x=None, width=dp(90))
        send_btn.bind(on_release=self.send)
        bottom.add_widget(self.input)
        bottom.add_widget(send_btn)
        root.add_widget(bottom)

        self.load_history()
        return root

    # ---------- chat ----------
    def add_bubble(self, text, mine):
        b = Bubble(text, mine)
        self.chat.add_widget(b)
        Clock.schedule_once(
            lambda dt_: setattr(self.scroll, "scroll_y", 0), 0.15)
        return b

    def load_history(self):
        rows = self.store.history(30)
        if not rows:
            self.add_bubble("Oi! Eu sou a Aurora. Digite /ajuda para ver "
                            "os comandos.", False)
        for r in rows:
            self.add_bubble(r["content"], r["role"] == "user")
        if not self.store.cfg["api_key"].strip():
            self.add_bubble("Para eu conversar com a IA, toque em Config "
                            "e cole a sua chave da API.", False)

    def send(self, *a):
        text = self.input.text.strip()
        if not text or self.busy:
            return
        self.input.text = ""
        Clock.schedule_once(lambda d: setattr(self.input, "focus", True), 0.1)
        self.add_bubble(text, True)
        reply = handle_command(self.store, text)
        if reply is not None:
            self.add_bubble(reply, False)
            return
        self.store.add_msg("user", text)
        self.busy = True
        self.thinking = self.add_bubble("Aurora está pensando...", False)
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        ok = True
        try:
            reply = ask_claude(self.store)
        except AuroraError as e:
            reply, ok = str(e), False
        except requests.exceptions.RequestException:
            reply, ok = ("Sem conexão com a internet ou o servidor não "
                         "respondeu. Tente de novo."), False
        except Exception as e:
            reply, ok = f"Erro inesperado: {e}", False
        if ok:
            self.store.add_msg("assistant", reply)
        Clock.schedule_once(lambda d: self._show(reply), 0)

    def _show(self, reply):
        if self.thinking is not None:
            self.thinking.text = reply
            self.thinking = None
        self.busy = False
        Clock.schedule_once(
            lambda dt_: setattr(self.scroll, "scroll_y", 0), 0.15)

    # ---------- configuracoes ----------
    def open_config(self, *a):
        cfg = self.store.cfg
        box = BoxLayout(orientation="vertical", spacing=dp(6),
                        padding=dp(10))

        def field(label, value, **kw):
            box.add_widget(Label(text=label, size_hint_y=None,
                                 height=dp(24), halign="left",
                                 text_size=(dp(300), None)))
            h = kw.pop("height", dp(42))
            t = TextInput(text=value, size_hint_y=None, height=h, **kw)
            box.add_widget(t)
            return t

        key = field("Chave da API", cfg["api_key"], multiline=False,
                    password=True)
        model = field("Modelo", cfg["model"], multiline=False)
        pers = field("Personalidade", cfg["personality"], multiline=True,
                     height=dp(130))

        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        cancel = Button(text="Cancelar")
        save = Button(text="Salvar")
        row.add_widget(cancel)
        row.add_widget(save)
        box.add_widget(row)

        pop = Popup(title="Configurações", content=box,
                    size_hint=(0.94, 0.85))

        def do_save(*_):
            cfg["api_key"] = key.text.strip()
            cfg["model"] = model.text.strip() or DEFAULT_CONFIG["model"]
            cfg["personality"] = (pers.text.strip()
                                  or DEFAULT_CONFIG["personality"])
            self.store.save_cfg()
            pop.dismiss()
            self.add_bubble("Configurações salvas.", False)

        save.bind(on_release=do_save)
        cancel.bind(on_release=pop.dismiss)
        pop.open()


if __name__ == "__main__":
    AuroraApp().run()

