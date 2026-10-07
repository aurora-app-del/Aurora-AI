# AURORA FRANKENSTEIN 1.0
# Interface Android para a Aurora 7.0.
# Voz -> Aurora.think() -> comandos Android -> voz.

import threading
import traceback

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

import aurora_7 as aurora
import aurora_android as android


class MessageLabel(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.text_size = (None, None)
        self.padding = (dp(12), dp(10))
        self.halign = 'left'
        self.valign = 'top'
        self.bind(texture_size=self._resize)

    def _resize(self, *_):
        self.height = self.texture_size[1] + dp(20)


class AuroraUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=dp(6), padding=dp(6), **kwargs)

        header = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        self.title = Label(text='AURORA', font_size='22sp', bold=True)
        self.status = Label(text='PRONTA', font_size='12sp', size_hint_x=None, width=dp(100))
        header.add_widget(self.title)
        header.add_widget(self.status)
        self.add_widget(header)

        self.scroll = ScrollView(size_hint=(1, 1))
        self.messages = BoxLayout(orientation='vertical', spacing=dp(6), size_hint_y=None)
        self.messages.bind(minimum_height=self.messages.setter('height'))
        self.scroll.add_widget(self.messages)
        self.add_widget(self.scroll)

        bottom = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(58), spacing=dp(5))
        self.input = TextInput(hint_text='Digite ou toque em OUVIR...', multiline=False, font_size='17sp')
        self.input.bind(on_text_validate=self.send)
        self.send_button = Button(text='ENVIAR', size_hint_x=None, width=dp(88))
        self.send_button.bind(on_release=self.send)
        self.mic_button = Button(text='🎙️ OUVIR', size_hint_x=None, width=dp(110))
        self.mic_button.bind(on_release=self.listen)
        bottom.add_widget(self.input)
        bottom.add_widget(self.send_button)
        bottom.add_widget(self.mic_button)
        self.add_widget(bottom)

        self.add_message('Aurora', 'Olá! Eu sou a Aurora. Toque em 🎙️ OUVIR e fale comigo. Também consigo abrir aplicativos e executar comandos Android permitidos.')

    def add_message(self, who, text):
        label = MessageLabel(text=f'[b]{who}[/b]\n{str(text)}', markup=True)
        self.messages.add_widget(label)
        Clock.schedule_once(lambda *_: setattr(self.scroll, 'scroll_y', 0), 0.05)

    def set_busy(self, busy, listening=False):
        self.send_button.disabled = busy
        self.input.disabled = busy
        self.mic_button.disabled = busy
        if listening:
            self.status.text = 'OUVINDO...'
            self.mic_button.text = '🎙️ ...'
        else:
            self.status.text = 'PROCESSANDO...' if busy else 'PRONTA'
            self.mic_button.text = '🎙️ OUVIR'

    def listen(self, *_):
        self.set_busy(True, listening=True)
        self.add_message('Aurora', 'Estou ouvindo...')
        android.listen_once(self._voice_received, self._voice_error)

    def _voice_received(self, text):
        Clock.schedule_once(lambda *_: self._handle_text(text, speak_response=True), 0)

    def _voice_error(self, error):
        Clock.schedule_once(lambda *_: self._finish(error, speak_response=True), 0)

    def send(self, *_):
        text = self.input.text.strip()
        if not text:
            return
        self.input.text = ''
        self._handle_text(text, speak_response=True)

    def _handle_text(self, text, speak_response=True):
        self.set_busy(True)
        self.add_message('Você', text)
        threading.Thread(target=self._process, args=(text, speak_response), daemon=True).start()

    def _process(self, text, speak_response):
        try:
            # 1) Primeiro tentamos uma ação Android determinística.
            action = android.execute_command(text)
            if action:
                if action.startswith('ACTION:OPENED:'):
                    answer = 'Abrindo ' + action.split(':', 2)[2] + '.'
                elif action == 'ACTION:SETTINGS':
                    answer = 'Abrindo as configurações.'
                elif action == 'ACTION:HOME':
                    answer = 'Voltando para a tela inicial.'
                elif action == 'ACTION:VOLUME_UP':
                    answer = 'Aumentando o volume.'
                elif action == 'ACTION:VOLUME_DOWN':
                    answer = 'Diminuindo o volume.'
                elif action == 'ACTION:SEARCH':
                    answer = 'Abrindo a pesquisa.'
                elif action == 'ACTION:BROWSER':
                    answer = 'Abrindo o navegador.'
                else:
                    answer = action
            else:
                # 2) Se não for comando, passa para o cérebro existente.
                answer = aurora.think(text)
        except Exception:
            answer = 'Tive um erro ao processar o comando.\n' + traceback.format_exc(limit=2)

        Clock.schedule_once(lambda *_: self._finish(answer, speak_response), 0)

    def _finish(self, answer, speak_response=True):
        self.add_message('Aurora', answer)
        self.set_busy(False)
        if speak_response:
            android.speak(answer)


class AuroraApp(App):
    title = 'Aurora'

    def build(self):
        return AuroraUI()


if __name__ == '__main__':
    AuroraApp().run()
