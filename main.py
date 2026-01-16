import sys
import time
import requests
import urllib3
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, 
                             QPushButton, QLabel, QSplitter, QMessageBox, 
                             QTextEdit, QScrollBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Отключаем предупреждения о небезопасном HTTPS
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- СТИЛИ ---
STYLESHEET = """
QMainWindow { background-color: #17212b; }
QWidget { color: #f5f5f5; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
QMessageBox { background-color: #17212b; }
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
        # Если не указан протокол, добавляем HTTPS
        if not url.startswith("http"):
            url = "https://" + url
        
        self.base_url = url
        self.auth = (user, password)
        self.headers = {'OCS-APIRequest': 'true', 'Accept': 'application/json'}

    def get_rooms(self):
        try:
            # --- ИСПРАВЛЕНИЕ ЗДЕСЬ: Добавлен /index.php ---
            # Было: /ocs/v2.php...
            # Стало: /index.php/ocs/v2.php...
            endpoint = f"{self.base_url}/index.php/ocs/v2.php/apps/spreed/api/v1/room"
            
            r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=10, verify=False)
            r.raise_for_status()
            return r.json()['ocs']['data'], None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return None, "Ошибка 401: Неверный логин/пароль.\nНужен App Password?"
            elif e.response.status_code == 404:
                return None, f"Ошибка 404 по адресу:\n{endpoint}\n\nСервер не нашел API. Проверьте адрес."
            else:
                return None, f"HTTP ошибка: {e}"
        except Exception as e:
            return None, f"Ошибка соединения: {str(e)}"

    def get_messages(self, token):
        try:
            # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
            endpoint = f"{self.base_url}/index.php/ocs/v2.php/apps/spreed/api/v1/chat/{token}"
            r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=5, verify=False)
            if r.status_code == 200:
                data = r.json()['ocs']['data']
                return list(reversed(data))
            return []
        except:
            return []

    def send_message(self, token, text):
        try:
            # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
            endpoint = f"{self.base_url}/index.php/ocs/v2.php/apps/spreed/api/v1/chat/{token}"
            r = requests.post(endpoint, auth=self.auth, headers=self.headers, json={'message': text}, verify=False)
            return r.status_code == 201
        except:
            return False

# --- ПОТОК ОБНОВЛЕНИЯ ---
class PollingThread(QThread):
    messages_updated = pyqtSignal(list)
    
    def __init__(self, api, token):
        super().__init__()
        self.api = api
        self.token = token
        self.running = True

    def run(self):
        last_id = 0
        while self.running:
            msgs = self.api.get_messages(self.token)
            if msgs:
                try:
                    current_last_id = msgs[-1]['id']
                    if current_last_id != last_id:
                        self.messages_updated.emit(msgs)
                        last_id = current_last_id
                except: pass
            time.sleep(2)

    def stop(self):
        self.running = False
        self.wait()

# --- ОКНО ВХОДА ---
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Вход")
        self.resize(350, 300)
        layout = QVBoxLayout()
        layout.setSpacing(15); layout.setContentsMargins(30, 30, 30, 30)
        
        self.url = QLineEdit(); self.url.setPlaceholderText("cloud.sk-technologies.org")
        # Для удобства можно сразу прописать ваш домен по умолчанию:
        self.url.setText("cloud.sk-technologies.org") 
        
        self.user = QLineEdit(); self.user.setPlaceholderText("Логин")
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("Пароль")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn = QPushButton("Войти")
        
        layout.addWidget(QLabel("Сервер:"))
        layout.addWidget(self.url)
        layout.addWidget(QLabel("Логин:"))
        layout.addWidget(self.user)
        layout.addWidget(QLabel("Пароль:"))
        layout.addWidget(self.pwd)
        layout.addWidget(self.btn)
        layout.addStretch()
        self.setLayout(layout)
        self.btn.clicked.connect(self.do_login)

    def do_login(self):
        self.btn.setEnabled(False); self.btn.setText("Подключение...")
        QApplication.processEvents()
        
        api = NextcloudAPI(self.url.text(), self.user.text(), self.pwd.text())
        rooms, error = api.get_rooms()
        
        if rooms is not None:
            self.main = ChatWindow(api, rooms, self.user.text())
            self.main.show()
            self.close()
        else:
            QMessageBox.critical(self, "Ошибка", error)
            self.btn.setEnabled(True); self.btn.setText("Войти")

# --- ОКНО ЧАТА ---
class ChatWindow(QMainWindow):
    def __init__(self, api, rooms, my_username):
        super().__init__()
        self.api = api; self.rooms = rooms; self.my_username = my_username
        self.worker = None; self.current_token = None
        self.setWindowTitle("NC Talk Lite")
        self.resize(1000, 700)
        
        central = QWidget(); self.setCentralWidget(central)
        layout = QHBoxLayout(central); layout.setContentsMargins(0,0,0,0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Список чатов
        self.room_list = QListWidget(); self.room_list.setFixedWidth(280)
        for room in rooms:
            name = room.get('displayName') or room.get('name') or "Чат"
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, room['token'])
            self.room_list.addItem(item)
        self.room_list.itemClicked.connect(self.open_chat)
        splitter.addWidget(self.room_list)
        
        # Чат
        right = QWidget(); r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(0,0,0,0); r_layout.setSpacing(0)
        self.header = QLabel("Выберите чат")
        self.header.setStyleSheet("padding: 15px; font-weight: bold; border-bottom: 1px solid #0e1621;")
        self.chat_area = QTextEdit(); self.chat_area.setReadOnly(True)
        
        inp_cont = QWidget(); inp_cont.setStyleSheet("padding: 10px; border-top: 1px solid #0e1621;")
        inp_l = QHBoxLayout(inp_cont); inp_l.setContentsMargins(5,5,5,5)
        self.inp = QLineEdit(); self.inp.setPlaceholderText("Сообщение...")
        self.inp.returnPressed.connect(self.send)
        btn = QPushButton("➤"); btn.setFixedWidth(50); btn.clicked.connect(self.send)
        inp_l.addWidget(self.inp); inp_l.addWidget(btn)
        
        r_layout.addWidget(self.header); r_layout.addWidget(self.chat_area); r_layout.addWidget(inp_cont)
        splitter.addWidget(right); layout.addWidget(splitter); splitter.setSizes([280, 720])

    def open_chat(self, item):
        token = item.data(Qt.ItemDataRole.UserRole)
        self.current_token = token
        self.header.setText(item.text())
        self.chat_area.clear()
        if self.worker: self.worker.stop()
        self.worker = PollingThread(self.api, token)
        self.worker.messages_updated.connect(self.render)
        self.worker.start()

    def render(self, msgs):
        html = "<style>a {color: #64b5f6; text-decoration: none;}</style>"
        for msg in msgs:
            is_me = (msg['actorId'] == self.my_username)
            color = "#2b5278" if is_me else "#182533"
            align = "right" if is_me else "left"
            sender = "" if is_me else f"<div style='color:#64b5f6; font-size:11px; font-weight:bold;'>{msg['actorDisplayName']}</div>"
            html += f"<div style='text-align:{align}; margin-bottom:5px;'><div style='background:{color}; padding:8px 12px; border-radius:8px; display:inline-block; text-align:left; max-width:75%;'>{sender}<span style='color:#fff;'>{msg['message']}</span></div></div>"
        self.chat_area.setHtml(html)
        sb = self.chat_area.verticalScrollBar(); sb.setValue(sb.maximum())

    def send(self):
        text = self.inp.text().strip()
        if text and self.current_token:
            if self.api.send_message(self.current_token, text): self.inp.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    LoginWindow().show()
    sys.exit(app.exec())
