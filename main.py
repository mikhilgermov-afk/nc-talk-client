import sys
import time
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, 
                             QPushButton, QLabel, QSplitter, QFrame, QMessageBox, 
                             QTextEdit, QAbstractItemView)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

# --- КОНФИГУРАЦИЯ ---
# Цветовая схема Telegram Desktop (Dark)
STYLESHEET = """
QMainWindow { background-color: #17212b; }
QWidget { color: #f5f5f5; font-family: 'Segoe UI', sans-serif; font-size: 14px; }

/* Боковая панель */
QListWidget { background-color: #0e1621; border: none; outline: none; }
QListWidget::item { padding: 10px; border-bottom: 1px solid #17212b; }
QListWidget::item:selected { background-color: #2b5278; }

/* Чат */
QTextEdit { background-color: #17212b; border: none; }
QLineEdit { background-color: #242f3d; border: 1px solid #17212b; padding: 10px; border-radius: 5px; color: white; }
QPushButton { background-color: #2b5278; color: white; border: none; padding: 10px 20px; font-weight: bold; border-radius: 5px; }
QPushButton:hover { background-color: #234565; }

/* Скроллбары */
QScrollBar:vertical { background: #0e1621; width: 10px; }
QScrollBar::handle:vertical { background: #566472; min-height: 20px; border-radius: 5px; }
"""

class NextcloudAPI:
    def __init__(self, url, user, password):
        self.base_url = url.rstrip('/')
        self.auth = (user, password)
        self.headers = {'OCS-APIRequest': 'true', 'Accept': 'application/json'}

    def get_rooms(self):
        try:
            r = requests.get(f"{self.base_url}/ocs/v2.php/apps/spreed/api/v1/room", 
                             auth=self.auth, headers=self.headers, timeout=5)
            r.raise_for_status()
            return r.json()['ocs']['data']
        except Exception as e:
            print(f"Error getting rooms: {e}")
            return []

    def get_messages(self, token):
        try:
            r = requests.get(f"{self.base_url}/ocs/v2.php/apps/spreed/api/v1/chat/{token}", 
                             auth=self.auth, headers=self.headers, timeout=5)
            r.raise_for_status()
            data = r.json()['ocs']['data']
            return list(reversed(data)) # Nextcloud отдает новые первыми
        except:
            return []

    def send_message(self, token, text):
        try:
            r = requests.post(f"{self.base_url}/ocs/v2.php/apps/spreed/api/v1/chat/{token}", 
                              auth=self.auth, headers=self.headers, json={'message': text})
            return r.status_code == 201
        except:
            return False

# --- ПОТОК ДЛЯ ОБНОВЛЕНИЯ ЧАТА ---
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
                # Простая проверка, изменилось ли что-то (в идеале сверять ID)
                current_last_id = msgs[-1]['id']
                if current_last_id != last_id:
                    self.messages_updated.emit(msgs)
                    last_id = current_last_id
            time.sleep(2) # Опрос раз в 2 секунды

    def stop(self):
        self.running = False
        self.wait()

# --- GUI ---
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NC Talk Login")
        self.resize(300, 250)
        self.setStyleSheet("background-color: #17212b; color: white;")
        
        layout = QVBoxLayout()
        self.url = QLineEdit(); self.url.setPlaceholderText("URL (https://cloud.site.ru)")
        self.user = QLineEdit(); self.user.setPlaceholderText("Username")
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("App Password")
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn = QPushButton("Войти")
        
        layout.addWidget(QLabel("Nextcloud Server:"))
        layout.addWidget(self.url)
        layout.addWidget(self.user)
        layout.addWidget(self.pwd)
        layout.addWidget(self.btn)
        
        self.setLayout(layout)
        self.btn.clicked.connect(self.do_login)

    def do_login(self):
        # Проверка соединения
        api = NextcloudAPI(self.url.text(), self.user.text(), self.pwd.text())
        rooms = api.get_rooms()
        if rooms:
            self.main = ChatWindow(api, rooms, self.user.text())
            self.main.show()
            self.close()
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось войти. Проверьте данные.")

class ChatWindow(QMainWindow):
    def __init__(self, api, rooms, my_username):
        super().__init__()
        self.api = api
        self.rooms = rooms
        self.my_username = my_username
        self.worker = None
        
        self.setWindowTitle("Nextcloud Talk (Native)")
        self.resize(900, 600)
        
        # Основной виджет и Layout
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0,0,0,0)
        
        # Сплиттер (разделяет список и чат)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # -- Левая панель (Список чатов) --
        self.room_list = QListWidget()
        self.room_list.setFixedWidth(250)
        for room in rooms:
            name = room.get('displayName') or room.get('name') or "Unnamed"
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, room['token'])
            self.room_list.addItem(item)
            
        self.room_list.itemClicked.connect(self.open_chat)
        splitter.addWidget(self.room_list)
        
        # -- Правая панель (Чат) --
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        
        # Заголовок чата
        self.header = QLabel("Выберите чат")
        self.header.setStyleSheet("background-color: #17212b; padding: 15px; font-weight: bold; border-bottom: 1px solid black;")
        
        # Область сообщений (Используем HTML для форматирования пузырей)
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        
        # Область ввода
        input_container = QWidget()
        input_container.setStyleSheet("background-color: #17212b; padding: 10px;")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0,0,0,0)
        
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
        layout.addWidget(splitter)
        
        # Разделитель по умолчанию
        splitter.setSizes([250, 650])

    def open_chat(self, item):
        token = item.data(Qt.ItemDataRole.UserRole)
        self.current_token = token
        self.header.setText(item.text())
        self.chat_area.clear()
        self.input_field.setFocus()
        
        # Запуск фонового потока для обновлений
        if self.worker: self.worker.stop()
        self.worker = PollingThread(self.api, token)
        self.worker.messages_updated.connect(self.update_ui_messages)
        self.worker.start()

    def update_ui_messages(self, msgs):
        # Формируем HTML чата
        html = "<style>p { margin: 5px; }</style>"
        for msg in msgs:
            sender = msg['actorDisplayName']
            text = msg['message']
            is_me = (msg['actorId'] == self.my_username)
            
            # Верстка "пузырей" на HTML (Qt поддерживает Subset HTML4)
            color = "#2b5278" if is_me else "#182533"
            align = "right" if is_me else "left"
            sender_html = "" if is_me else f"<div style='color:#74b9ff; font-size:10px; font-weight:bold;'>{sender}</div>"
            
            html += f"""
            <div style='width:100%; text-align:{align};'>
                <div style='background-color:{color}; padding:8px; border-radius:10px; display:inline-block; text-align:left;'>
                    {sender_html}
                    <span style='color:#fff;'>{text}</span>
                </div>
            </div>
            <br>
            """
        
        # Запоминаем позицию скролла, чтобы не прыгало, если мы читаем историю (упрощенно - всегда вниз)
        self.chat_area.setHtml(html)
        sb = self.chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send_msg(self):
        text = self.input_field.text().strip()
        if not text or not hasattr(self, 'current_token'): return
        
        # Отправляем (блокирующе для простоты, лучше тоже в поток)
        if self.api.send_message(self.current_token, text):
            self.input_field.clear()
            # Поток сам подтянет сообщение через секунду

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    
    login = LoginWindow()
    login.show()
    
    sys.exit(app.exec())
