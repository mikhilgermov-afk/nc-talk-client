import sys
import traceback
import time
import requests
import urllib3

# --- ЛОВУШКА ДЛЯ ОШИБОК ---
def excepthook(exc_type, exc_value, exc_tb):
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("КРИТИЧЕСКАЯ ОШИБКА:", tb)
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            QMessageBox.critical(None, "Критическая ошибка", tb)
    except: pass

sys.excepthook = excepthook
# ---------------------------

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, 
                             QPushButton, QLabel, QSplitter, QMessageBox, 
                             QTextEdit, QScrollBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- СТИЛИ ---
STYLESHEET = """
QMainWindow { background-color: #17212b; }
QWidget { color: #f5f5f5; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
QMessageBox { background-color: #17212b; color: #f5f5f5; }
QListWidget { background-color: #0e1621; border: none; outline: none; }
QListWidget::item { padding: 12px; border-bottom: 1px solid #17212b; }
QListWidget::item:selected { background-color: #2b5278; }
QTextEdit { background-color: #17212b; border: none; }
QLineEdit { background-color: #242f3d; border: 1px solid #17212b; padding: 10px; border-radius: 5px; color: white; }
QPushButton { background-color: #5288c1; color: white; border: none; padding: 10px 20px; font-weight: bold; border-radius: 5px; }
QPushButton:hover { background-color: #4674a2; }
"""

class NextcloudAPI:
    def __init__(self, url, user, password):
        url = url.strip().rstrip('/')
        
        # ЕСЛИ ПОЛЬЗОВАТЕЛЬ НЕ НАПИСАЛ HTTP/HTTPS, ПОДСТАВЛЯЕМ HTTPS
        if not url.startswith("http"):
            url = "https://" + url
            
        self.base_url = url
        self.auth = (user, password)
        
        # Маскируемся под браузер
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'OCS-APIRequest': 'true',
            'Accept': 'application/json'
        }
        
        # Используем путь, подтвержденный через curl
        self.api_prefix = "/index.php/ocs/v2.php/apps/spreed/api/v1"

    def get_rooms(self):
        endpoint = f"{self.base_url}{self.api_prefix}/room"
        try:
            # verify=False - игнорируем ошибки сертификата
            r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=15, verify=False)
            
            if r.status_code == 401:
                return None, "Ошибка 401: Неверный пароль!\nПроверьте логин и используйте App Password."
            
            if r.status_code == 404:
                 # ВОТ ЗДЕСЬ МЫ СМОТРИМ, КТО ОТВЕТИЛ 404
                 response_text = r.text[:500] # Берем первые 500 символов ответа
                 return None, f"Ошибка 404 (Не найдено).\n\nАдрес: {endpoint}\n\nОТВЕТ СЕРВЕРА (Покажите это разработчику):\n{response_text}"

            r.raise_for_status()
            return r.json()['ocs']['data'], None
            
        except Exception as e:
            return None, f"Ошибка соединения:\n{str(e)}"

    def get_messages(self, token):
        try:
            endpoint = f"{self.base_url}{self.api_prefix}/chat/{token}"
            r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=5, verify=False)
            if r.status_code == 200:
                return list(reversed(r.json()['ocs']['data']))
            return []
        except:
            return []

    def send_message(self, token, text):
        try:
            endpoint = f"{self.base_url}{self.api_prefix}/chat/{token}"
            r = requests.post(endpoint, auth=self.auth, headers=self.headers, json={'message': text}, verify=False)
            return r.status_code == 201
        except:
            return False

class PollingThread(QThread):
    messages_updated = pyqtSignal(list)
    def __init__(self, api, token):
        super().__init__(); self.api = api; self.token = token; self.running = True
    def run(self):
        last_id = 0
        while self.running:
            msgs = self.api.get_messages(self.token)
            if msgs:
                try:
                    if msgs[-1]['id'] != last_id:
                        self.messages_updated.emit(msgs); last_id = msgs[-1]['id']
                except: pass
            time.sleep(2)
    def stop(self): self.running = False; self.wait()

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Вход")
        self.resize(400, 350)
        l = QVBoxLayout()
        
        self.url = QLineEdit()
        # По умолчанию ставим ваш домен
        self.url.setText("cloud.sk-technologies.org")
        
        self.user = QLineEdit(); self.user.setPlaceholderText("Логин")
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("Пароль приложения")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn = QPushButton("Войти")
        
        l.addWidget(QLabel("Сервер (попробуйте http:// если https не работает):")); l.addWidget(self.url)
        l.addWidget(QLabel("Логин:")); l.addWidget(self.user)
        l.addWidget(QLabel("Пароль приложения:")); l.addWidget(self.pwd)
        l.addWidget(self.btn); l.addStretch()
        self.setLayout(l); self.btn.clicked.connect(self.do_login)

    def do_login(self):
        self.btn.setEnabled(False); self.btn.setText("Вход...")
        QApplication.processEvents()
        
        api = NextcloudAPI(self.url.text(), self.user.text(), self.pwd.text())
        rooms, error = api.get_rooms()
        
        if rooms is not None:
            self.main_window = ChatWindow(api, rooms, self.user.text())
            self.main_window.show(); self.close()
        else:
            QMessageBox.critical(self, "Ошибка", str(error))
            self.btn.setEnabled(True); self.btn.setText("Войти")

class ChatWindow(QMainWindow):
    def __init__(self, api, rooms, my_username):
        super().__init__()
        self.api = api; self.rooms = rooms; self.my_username = my_username
        self.worker = None; self.current_token = None
        self.setWindowTitle("NC Talk Lite")
        self.resize(1000, 700)
        c = QWidget(); self.setCentralWidget(c)
        l = QHBoxLayout(c); l.setContentsMargins(0,0,0,0)
        split = QSplitter(Qt.Orientation.Horizontal)
        
        self.list = QListWidget(); self.list.setFixedWidth(280)
        for r in rooms:
            name = r.get('displayName') or r.get('name') or "Chat"
            it = QListWidgetItem(name); it.setData(Qt.ItemDataRole.UserRole, r['token'])
            self.list.addItem(it)
        self.list.itemClicked.connect(self.open_chat)
        split.addWidget(self.list)
        
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        self.head = QLabel("Чат"); self.head.setStyleSheet("padding: 15px; font-weight: bold; border-bottom: 1px solid #000;")
        self.chat = QTextEdit(); self.chat.setReadOnly(True)
        inp_box = QWidget(); il = QHBoxLayout(inp_box)
        self.inp = QLineEdit(); btn = QPushButton("➤"); btn.setFixedWidth(40)
        self.inp.returnPressed.connect(self.send); btn.clicked.connect(self.send)
        il.addWidget(self.inp); il.addWidget(btn)
        
        rl.addWidget(self.head); rl.addWidget(self.chat); rl.addWidget(inp_box)
        split.addWidget(right); l.addWidget(split); split.setSizes([280, 720])

    def open_chat(self, item):
        token = item.data(Qt.ItemDataRole.UserRole)
        self.current_token = token; self.head.setText(item.text())
        self.chat.clear()
        if self.worker: self.worker.stop()
        self.worker = PollingThread(self.api, token)
        self.worker.messages_updated.connect(self.render)
        self.worker.start()

    def render(self, msgs):
        h = "<style>a{color:#64b5f6; text-decoration:none}</style>"
        for m in msgs:
            me = (m['actorId'] == self.my_username)
            col = "#2b5278" if me else "#182533"
            align = "right" if me else "left"
            nm = "" if me else f"<div style='color:#64b5f6; font-size:10px;'>{m['actorDisplayName']}</div>"
            h += f"<div style='text-align:{align}; margin:5px;'><div style='background:{col}; padding:8px; border-radius:8px; display:inline-block; text-align:left;'>{nm}<span style='color:#fff'>{m['message']}</span></div></div>"
        self.chat.setHtml(h)
        sb = self.chat.verticalScrollBar(); sb.setValue(sb.maximum())

    def send(self):
        txt = self.inp.text().strip()
        if txt and self.current_token:
            if self.api.send_message(self.current_token, txt): self.inp.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = LoginWindow()
    window.show()
    sys.exit(app.exec())
