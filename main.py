import sys
import time
import requests
import urllib3
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, 
                             QPushButton, QLabel, QSplitter, QMessageBox, 
                             QTextEdit, QAbstractItemView)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QScrollBar

# Отключаем предупреждения о небезопасном HTTPS (так как мы разрешаем self-signed)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- СТИЛИ (Dark Telegram Theme) ---
STYLESHEET = """
QMainWindow { background-color: #17212b; }
QWidget { color: #f5f5f5; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
QMessageBox { background-color: #17212b; }

/* Боковая панель */
QListWidget { background-color: #0e1621; border: none; outline: none; }
QListWidget::item { padding: 12px; border-bottom: 1px solid #17212b; }
QListWidget::item:selected { background-color: #2b5278; }

/* Чат */
QTextEdit { background-color: #17212b; border: none; }
QLineEdit { background-color: #242f3d; border: 1px solid #17212b; padding: 10px; border-radius: 5px; color: white; }
QPushButton { background-color: #5288c1; color: white; border: none; padding: 10px 20px; font-weight: bold; border-radius: 5px; }
QPushButton:hover { background-color: #4674a2; }
"""

class NextcloudAPI:
    def __init__(self, url, user, password):
        # Авто-исправление URL
        url = url.strip().rstrip('/')
        if not url.startswith("http"):
            url = "https://" + url
        
        self.base_url = url
        self.auth = (user, password)
        self.headers = {'OCS-APIRequest': 'true', 'Accept': 'application/json'}

    def get_rooms(self):
        """Возвращает кортеж: (список_комнат, текст_ошибки)"""
        try:
            # verify=False позволяет работать с самоподписанными сертификатами
            r = requests.get(f"{self.base_url}/ocs/v2.php/apps/spreed/api/v1/room", 
                             auth=self.auth, headers=self.headers, timeout=10, verify=False)
            r.raise_for_status()
            return r.json()['ocs']['data'], None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return None, "Ошибка 401: Неверный логин или пароль.\nЕсли включен 2FA, используйте 'Пароль приложения'."
            elif e.response.status_code == 404:
                return None, "Ошибка 404: API не найден.\nПроверьте адрес сервера."
            else:
                return None, f"HTTP ошибка: {e}"
        except Exception as e:
            return None, f"Ошибка соединения: {str(e)}"

    def get_messages(self, token):
        try:
            r = requests.get(f"{self.base_url}/ocs/v2.php/apps/spreed/api/v1/chat/{token}", 
                             auth=self.auth, headers=self.headers, timeout=5, verify=False)
            if r.status_code == 200:
                data = r.json()['ocs']['data']
                return list(reversed(data))
            return []
        except:
            return []

    def send_message(self, token, text):
        try:
            r = requests.post(f"{self.base_url}/ocs/v2.php/apps/spreed/api/v1/chat/{token}", 
                              auth=self.auth, headers=self.headers, json={'message': text}, verify=False)
            return r.status_code == 201
        except:
            return False

# --- ПОТОК ФОНОВОГО ОБНОВЛЕНИЯ ---
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
                # Проверяем ID последнего сообщения, чтобы не перерисовывать зря
                current_last_id = msgs[-1]['id']
                if current_last_id != last_id:
                    self.messages_updated.emit(msgs)
                    last_id = current_last_id
            time.sleep(2) # Интервал опроса

    def stop(self):
        self.running = False
        self.wait()

# --- ОКНО ВХОДА ---
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NC Talk Login")
        self.resize(350, 300)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Вход в Nextcloud Talk")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.url = QLineEdit(); self.url.setPlaceholderText("Адрес сервера (cloud.mysite.ru)")
        self.user = QLineEdit(); self.user.setPlaceholderText("Логин")
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("Пароль (или App Password)")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        
        self.btn = QPushButton("Войти")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout.addWidget(title)
        layout.addWidget(QLabel("Сервер:"))
        layout.addWidget(self.url)
        layout.addWidget(QLabel("Пользователь:"))
        layout.addWidget(self.user)
        layout.addWidget(QLabel("Пароль:"))
        layout.addWidget(self.pwd)
        layout.addWidget(self.btn)
        layout.addStretch()
        
        self.setLayout(layout)
        self.btn.clicked.connect(self.do_login)

    def do_login(self):
        self.btn.setText("Подключение...")
        self.btn.setEnabled(False)
        QApplication.processEvents() # Обновить UI
        
        api = NextcloudAPI(self.url.text(), self.user.text(), self.pwd.text())
        rooms, error = api.get_rooms()
        
        if rooms is not None:
            self.main = ChatWindow(api, rooms, self.user.text())
            self.main.show()
            self.close()
        else:
            QMessageBox.critical(self, "Ошибка входа", error)
            self.btn.setText("Войти")
            self.btn.setEnabled(True)

# --- ГЛАВНОЕ ОКНО ЧАТА ---
class ChatWindow(QMainWindow):
    def __init__(self, api, rooms, my_username):
        super().__init__()
        self.api = api
        self.rooms = rooms
        self.my_username = my_username
        self.worker = None
        self.current_token = None
        
        self.setWindowTitle("Nextcloud Talk Lite")
        self.resize(1000, 700)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0,0,0,0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 1. Список чатов
        self.room_list = QListWidget()
        self.room_list.setFixedWidth(280)
        for room in rooms:
            name = room.get('displayName') or room.get('name') or "Без названия"
            item = QListWidgetItem(name)
            # Сохраняем токен комнаты внутри элемента списка
            item.setData(Qt.ItemDataRole.UserRole, room['token'])
            self.room_list.addItem(item)
            
        self.room_list.itemClicked.connect(self.open_chat)
        splitter.addWidget(self.room_list)
        
        # 2. Область чата
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        right_layout.setSpacing(0)
        
        # Хедер чата
        self.header = QLabel("Выберите чат")
        self.header.setStyleSheet("background-color: #17212b; padding: 15px; font-weight: bold; border-bottom: 1px solid #0e1621;")
        
        # История сообщений
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        
        # Панель ввода
        input_container = QWidget()
        input_container.setStyleSheet("background-color: #17212b; padding: 10px; border-top: 1px solid #0e1621;")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(5,5,5,5)
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Написать сообщение...")
        self.input_field.returnPressed.connect(self.send_msg)
        
        send_btn = QPushButton("➤")
        send_btn.setFixedWidth(50)
        send_btn.clicked.connect(self.send_msg)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(send_btn)
        
        right_layout.addWidget(self.header)
        right_layout.addWidget(self.chat_area)
        right_layout.addWidget(input_container)
        
        splitter.addWidget(right_panel)
        main_layout.addWidget(splitter)
        splitter.setSizes([280, 720])

    def open_chat(self, item):
        token = item.data(Qt.ItemDataRole.UserRole)
        self.current_token = token
        self.header.setText(item.text())
        self.chat_area.clear()
        self.input_field.setFocus()
        
        # Перезапуск поллинга
        if self.worker: self.worker.stop()
        self.worker = PollingThread(self.api, token)
        self.worker.messages_updated.connect(self.render_messages)
        self.worker.start()

    def render_messages(self, msgs):
        # Формируем HTML
        html = "<style>a {color: #64b5f6; text-decoration: none;}</style>"
        for msg in msgs:
            sender = msg['actorDisplayName']
            text = msg['message']
            # Замена переносов строк на <br>
            text = text.replace('\n', '<br>')
            
            is_me = (msg['actorId'] == self.my_username)
            
            # Цвета
            bg_color = "#2b5278" if is_me else "#182533"
            align = "right" if is_me else "left"
            
            # Имя отправителя (только для чужих сообщений)
            sender_html = "" 
            if not is_me:
                sender_html = f"<div style='color:#64b5f6; font-size:11px; font-weight:bold; margin-bottom:2px;'>{sender}</div>"
            
            # Верстка баббла
            html += f"""
            <div style='width:100%; text-align:{align}; margin-bottom: 5px;'>
                <div style='background-color:{bg_color}; padding:8px 12px; border-radius:8px; display:inline-block; text-align:left; max-width:70%;'>
                    {sender_html}
                    <span style='color:#fff; font-size:14px;'>{text}</span>
                </div>
            </div>
            """
        
        self.chat_area.setHtml(html)
        # Прокрутка вниз
        sb = self.chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send_msg(self):
        text = self.input_field.text().strip()
        if not text or not self.current_token: return
        
        success = self.api.send_message(self.current_token, text)
        if success:
            self.input_field.clear()
            # Поток подгрузит сообщение через секунду

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    
    login = LoginWindow()
    login.show()
    
    sys.exit(app.exec())
