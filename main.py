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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        if not url.startswith("http"):
            url = "https://" + url
        
        self.base_url = url
        self.auth = (user, password)
        self.headers = {'OCS-APIRequest': 'true', 'Accept': 'application/json'}
        self.working_prefix = None # Сюда мы запишем найденный путь

    def _find_working_endpoint(self):
        """Перебирает варианты путей, чтобы найти рабочий API"""
        
        # Варианты путей, которые бывают в Nextcloud
        candidates = [
            "/ocs/v2.php/apps/spreed/api/v1",           # Стандарт
            "/index.php/ocs/v2.php/apps/spreed/api/v1", # Без rewrite rules
            "/nextcloud/ocs/v2.php/apps/spreed/api/v1", # В подпапке
            "/index.php/apps/spreed/api/v1"             # Прямой доступ к приложению
        ]

        print(f"Ищу API на сервере: {self.base_url}")
        
        last_error = ""
        
        for prefix in candidates:
            endpoint = f"{self.base_url}{prefix}/room"
            try:
                # verify=False для самоподписанных сертификатов
                r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=5, verify=False)
                
                print(f"Проверка {endpoint} -> Код {r.status_code}")
                
                # Если 200 (ОК) или 401 (Требует пароль, значит путь верный)
                if r.status_code == 200:
                    self.working_prefix = prefix
                    return r.json()['ocs']['data'], None
                elif r.status_code == 401:
                    return None, "Ошибка 401: Пароль не подходит (но сервер найден!)"
                elif r.status_code == 404:
                    continue # Ищем дальше
                else:
                    last_error = f"Ошибка HTTP {r.status_code} по адресу {endpoint}"
            except Exception as e:
                last_error = f"Ошибка соединения: {e}"
        
        return None, f"Не удалось найти API Talk.\nПоследняя ошибка: {last_error}\n\nПробовали варианты:\n" + "\n".join(candidates)

    def get_rooms(self):
        # Если мы еще не знаем правильный путь, ищем его
        if not self.working_prefix:
            data, error = self._find_working_endpoint()
            if error: return None, error
            # Если _find_working_endpoint вернул данные, значит он уже сходил за комнатами
            if data is not None: return data, None
        
        # Если путь уже известен
        endpoint = f"{self.base_url}{self.working_prefix}/room"
        try:
            r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=10, verify=False)
            r.raise_for_status()
            return r.json()['ocs']['data'], None
        except Exception as e:
            return None, str(e)

    def get_messages(self, token):
        if not self.working_prefix: return []
        try:
            endpoint = f"{self.base_url}{self.working_prefix}/chat/{token}"
            r = requests.get(endpoint, auth=self.auth, headers=self.headers, timeout=5, verify=False)
            if r.status_code == 200:
                return list(reversed(r.json()['ocs']['data']))
            return []
        except:
            return []

    def send_message(self, token, text):
        if not self.working_prefix: return False
        try:
            endpoint = f"{self.base_url}{self.working_prefix}/chat/{token}"
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
        self.resize(350, 300)
        l = QVBoxLayout()
        self.url = QLineEdit(); self.url.setText("cloud.sk-technologies.org")
        self.user = QLineEdit(); self.user.setPlaceholderText("Логин")
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("Пароль")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn = QPushButton("Войти")
        l.addWidget(QLabel("Сервер:")); l.addWidget(self.url)
        l.addWidget(QLabel("Логин:")); l.addWidget(self.user)
        l.addWidget(QLabel("Пароль:")); l.addWidget(self.pwd)
        l.addWidget(self.btn); l.addStretch()
        self.setLayout(l); self.btn.clicked.connect(self.do_login)

    def do_login(self):
        self.btn.setEnabled(False); self.btn.setText("Поиск сервера...")
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
