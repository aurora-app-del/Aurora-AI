# Aurora Android bridge - usa apenas APIs do Android via PyJNIus.
# Em desktop/Pydroid, as funções falham de forma segura em vez de quebrar o app.

import re
import threading
import urllib.parse

try:
    from jnius import autoclass, cast
    from android.runnable import run_on_ui_thread
    ANDROID = True
except Exception:
    ANDROID = False

if ANDROID:
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Intent = autoclass('android.content.Intent')
    Uri = autoclass('android.net.Uri')
    Settings = autoclass('android.provider.Settings')
    Build = autoclass('android.os.Build')
    SpeechRecognizer = autoclass('android.speech.SpeechRecognizer')
    RecognizerIntent = autoclass('android.speech.RecognizerIntent')
    TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
    Locale = autoclass('java.util.Locale')
    AudioManager = autoclass('android.media.AudioManager')
    ApplicationInfo = autoclass('android.content.pm.ApplicationInfo')


def _activity():
    return PythonActivity.mActivity if ANDROID else None


def speak(text, on_done=None):
    """Fala texto usando Android TTS. Retorna False fora do Android."""
    if not ANDROID:
        return False

    text = str(text).strip()
    if not text:
        return False

    def worker():
        try:
            activity = _activity()
            tts = TextToSpeech(activity, None)
            # Aguarda inicialização do TTS sem bloquear a UI por muito tempo.
            for _ in range(50):
                try:
                    ready = int(tts.getEngines().size()) >= 0
                except Exception:
                    ready = False
                if ready:
                    break
                import time
                time.sleep(0.05)

            try:
                tts.setLanguage(Locale('pt', 'BR'))
            except Exception:
                try:
                    tts.setLanguage(Locale.getDefault())
                except Exception:
                    pass

            try:
                tts.setSpeechRate(1.0)
                tts.setPitch(1.0)
            except Exception:
                pass

            # QUEUE_FLUSH = 0
            tts.speak(text, 0, None, 'AURORA')
            if on_done:
                on_done()
        except Exception:
            if on_done:
                on_done()

    threading.Thread(target=worker, daemon=True).start()
    return True


def stop_speaking():
    # O TTS é criado por chamada para reduzir estado global. Android cuidará
    # do áudio quando a fala terminar; não é crítico para o primeiro MVP.
    return True


def listen_once(callback, error_callback=None, language='pt-BR'):
    """Abre o reconhecedor de fala e retorna uma única transcrição."""
    if not ANDROID:
        if error_callback:
            error_callback('Reconhecimento de voz só funciona no Android.')
        return False

    if not SpeechRecognizer.isRecognitionAvailable(_activity()):
        if error_callback:
            error_callback('O reconhecimento de voz não está disponível neste aparelho.')
        return False

    try:
        recognizer = SpeechRecognizer.createSpeechRecognizer(_activity())

        class Listener:
            def onReadyForSpeech(self, params):
                pass
            def onBeginningOfSpeech(self):
                pass
            def onRmsChanged(self, rmsdB):
                pass
            def onBufferReceived(self, buffer):
                pass
            def onEndOfSpeech(self):
                pass
            def onError(self, error):
                try:
                    recognizer.destroy()
                except Exception:
                    pass
                if error_callback:
                    error_callback('Não consegui entender. Tente falar novamente.')
            def onResults(self, results):
                try:
                    arr = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    text = str(arr.get(0)) if arr and arr.size() else ''
                    recognizer.destroy()
                    if text:
                        callback(text)
                    elif error_callback:
                        error_callback('Não ouvi nenhuma frase.')
                except Exception as exc:
                    try:
                        recognizer.destroy()
                    except Exception:
                        pass
                    if error_callback:
                        error_callback(str(exc))
            def onPartialResults(self, partialResults):
                pass
            def onEvent(self, eventType, params):
                pass

        listener = Listener()
        recognizer.setRecognitionListener(listener)

        intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                        RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, language)
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, False)
        recognizer.startListening(intent)
        return True
    except Exception as exc:
        if error_callback:
            error_callback(f'Falha no microfone: {exc}')
        return False


def _normalize(s):
    import unicodedata
    s = unicodedata.normalize('NFD', str(s).lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def _clean_command(text):
    t = str(text).strip()
    n = _normalize(t)
    # Remove palavra de ativação quando o reconhecimento capturar "Aurora ...".
    n = re.sub(r'^\s*aurora[,:;.!]?\s*', '', n).strip()
    return n


def _launch_package(package_name):
    pm = _activity().getPackageManager()
    intent = pm.getLaunchIntentForPackage(package_name)
    if intent is None:
        return False
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    _activity().startActivity(intent)
    return True


def find_and_launch_app(name):
    """Procura um aplicativo instalado pelo nome visível e abre sua activity principal."""
    if not ANDROID:
        return False, 'Só funciona no Android.'

    wanted = _normalize(name).strip()
    aliases = {
        'whatsapp': 'com.whatsapp',
        'youtube': 'com.google.android.youtube',
        'chrome': 'com.android.chrome',
        'google chrome': 'com.android.chrome',
        'instagram': 'com.instagram.android',
        'spotify': 'com.spotify.music',
        'telegram': 'org.telegram.messenger',
        'facebook': 'com.facebook.katana',
        'tiktok': 'com.zhiliaoapp.musically',
    }
    if wanted in aliases:
        if _launch_package(aliases[wanted]):
            return True, wanted

    try:
        pm = _activity().getPackageManager()
        apps = pm.getInstalledApplications(0)
        for i in range(apps.size()):
            info = apps.get(i)
            try:
                label = str(info.loadLabel(pm))
            except Exception:
                label = ''
            if _normalize(label).strip() == wanted:
                package_name = str(info.packageName)
                if _launch_package(package_name):
                    return True, label
    except Exception as exc:
        return False, str(exc)

    return False, name


def open_url(url):
    if not ANDROID:
        return False
    try:
        uri = Uri.parse(str(url))
        intent = Intent(Intent.ACTION_VIEW, uri)
        _activity().startActivity(intent)
        return True
    except Exception:
        return False


def web_search(query):
    q = urllib.parse.quote_plus(str(query).strip())
    return open_url('https://www.google.com/search?q=' + q)


def open_settings():
    if not ANDROID:
        return False
    try:
        _activity().startActivity(Intent(Settings.ACTION_SETTINGS))
        return True
    except Exception:
        return False


def go_home():
    if not ANDROID:
        return False
    try:
        intent = Intent(Intent.ACTION_MAIN)
        intent.addCategory(Intent.CATEGORY_HOME)
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        _activity().startActivity(intent)
        return True
    except Exception:
        return False


def set_volume(kind='media', delta=1):
    if not ANDROID:
        return False
    try:
        am = cast('android.media.AudioManager',
                  _activity().getSystemService('audio'))
        stream = AudioManager.STREAM_MUSIC
        if kind == 'ring':
            stream = AudioManager.STREAM_RING
        elif kind == 'alarm':
            stream = AudioManager.STREAM_ALARM
        elif kind == 'notification':
            stream = AudioManager.STREAM_NOTIFICATION
        direction = AudioManager.ADJUST_RAISE if delta > 0 else AudioManager.ADJUST_LOWER
        for _ in range(min(abs(int(delta)), 10)):
            am.adjustStreamVolume(stream, direction, AudioManager.FLAG_SHOW_UI)
        return True
    except Exception:
        return False


def execute_command(text):
    """Executa comandos simples e determinísticos. Retorna resposta ou None."""
    original = str(text).strip()
    q = _clean_command(original)

    if not q:
        return 'Sim?'

    # Apps.
    patterns = [
        r'^(?:abra|abrir|abre|inicie|iniciar|inicia)\s+(?:o|a)?\s*(.+)$',
        r'^(?:abra|abrir|abre)\s+(?:meu|minha)?\s*(.+)$',
    ]
    for pat in patterns:
        m = re.match(pat, q)
        if m:
            name = m.group(1).strip()
            # Não trate navegador/ajustes como app genérico.
            if name in ('configuracoes', 'configuracao', 'ajustes', 'settings'):
                return 'ACTION:SETTINGS' if open_settings() else 'Não consegui abrir as configurações.'
            if name in ('navegador', 'internet'):
                return 'ACTION:BROWSER'
            ok, found = find_and_launch_app(name)
            if ok:
                return f'ACTION:OPENED:{found}'
            return f'Não encontrei o aplicativo "{name}".'

    if q in ('abra configuracoes', 'abra a configuracao', 'abra os ajustes', 'abra settings'):
        return 'ACTION:SETTINGS' if open_settings() else 'Não consegui abrir as configurações.'

    if q in ('volte para a tela inicial', 'voltar para tela inicial', 'ir para tela inicial', 'inicio', 'tela inicial'):
        return 'ACTION:HOME' if go_home() else 'Não consegui voltar à tela inicial.'

    if q in ('aumente o volume', 'aumenta o volume', 'volume mais', 'aumentar volume'):
        return 'ACTION:VOLUME_UP' if set_volume(delta=3) else 'Não consegui alterar o volume.'

    if q in ('diminua o volume', 'diminui o volume', 'volume menos', 'diminuir volume'):
        return 'ACTION:VOLUME_DOWN' if set_volume(delta=-3) else 'Não consegui alterar o volume.'

    m = re.match(r'^(?:pesquise|pesquisar|procure|buscar|busque)\s+(?:na internet|no google|na web)?\s*(.+)$', q)
    if m:
        query = m.group(1).strip()
        return 'ACTION:SEARCH' if web_search(query) else 'Não consegui abrir a pesquisa.'

    if q in ('abra o navegador', 'abrir navegador', 'abre o navegador'):
        return 'ACTION:BROWSER' if open_url('https://www.google.com') else 'Não consegui abrir o navegador.'

    return None
