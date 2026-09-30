
# Aurora App 1.0
# Interface Android para a Aurora 7.0.
#
# Coloque aurora_7.py na mesma pasta deste arquivo.
# Em Android, a aplicação usa Kivy/KivyMD quando disponíveis.
# O motor continua sendo o arquivo aurora_7.py.

import os
import sys
import threading
import traceback

try:
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.metrics import dp
    from kivy.properties import StringProperty
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.textinput import TextInput
except ImportError:
    raise SystemExit(
        "Kivy não está instalado. Instale Kivy antes de executar a Aurora App."
    )

# Importa o motor existente.
try:
    import aurora_7 as aurora
except Exception as exc:
    raise SystemExit(
        "Não foi possível carregar aurora_7.py:\n" + str(exc)
    )


class MessageLabel(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.text_size = (None, None)
        self.padding = (dp(12), dp(10))
        self.halign = "left"
        self.valign = "top"
        self.bind(texture_size=self._resize)

    def _resize(self, *_):
        self.height = self.texture_size[1] + dp(20)


class AuroraUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            spacing=dp(6),
            padding=dp(6),
            **kwargs
        )

        self.title = Label(
            text="AURORA",
            size_hint_y=None,
            height=dp(48),
            font_size="22sp",
            bold=True
        )
        self.add_widget(self.title)

        self.scroll = ScrollView(size_hint=(1, 1))
        self.messages = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_y=None
        )
        self.messages.bind(minimum_height=self.messages.setter("height"))
        self.scroll.add_widget(self.messages)
        self.add_widget(self.scroll)

        bottom = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(58),
            spacing=dp(5)
        )

        self.input = TextInput(
            hint_text="Digite sua pergunta...",
            multiline=False,
            font_size="17sp"
        )
        self.input.bind(on_text_validate=self.send)

        self.send_button = Button(
            text="ENVIAR",
            size_hint_x=None,
            width=dp(95)
        )
        self.send_button.bind(on_release=self.send)

        bottom.add_widget(self.input)
        bottom.add_widget(self.send_button)
        self.add_widget(bottom)

        self.add_message(
            "Aurora",
            "Olá! Sou a Aurora. Pergunte qualquer coisa dentro do que "
            "eu conseguir processar e, quando configurada, posso pesquisar "
            "informações na internet."
        )

    def add_message(self, who, text):
        label = MessageLabel(
            text=f"[b]{who}[/b]\n{text}",
            markup=True
        )
        self.messages.add_widget(label)
        Clock.schedule_once(
            lambda *_: setattr(
                self.scroll, "scroll_y", 0
            ),
            0.05
        )

    def set_busy(self, busy):
        self.send_button.disabled = busy
        self.input.disabled = busy
        self.send_button.text = "..." if busy else "ENVIAR"

    def send(self, *_):
        text = self.input.text.strip()
        if not text:
            return

        self.input.text = ""
        self.add_message("Você", text)
        self.set_busy(True)

        threading.Thread(
            target=self._process,
            args=(text,),
            daemon=True
        ).start()

    def _process(self, text):
        try:
            # Usa o pipeline principal da Aurora.
            answer = aurora.think(text)
            if answer is None:
                answer = "Não consegui gerar uma resposta."
        except Exception:
            answer = "Erro interno:\n" + traceback.format_exc()

        Clock.schedule_once(
            lambda *_: self._finish(answer),
            0
        )

    def _finish(self, answer):
        self.add_message("Aurora", str(answer))
        self.set_busy(False)


class AuroraApp(App):
    title = "Aurora"

    def build(self):
        return AuroraUI()


if __name__ == "__main__":
    AuroraApp().run()
