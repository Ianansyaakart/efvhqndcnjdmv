# main.py
import asyncio
import json
import uuid
import os
import mimetypes
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pathlib import Path
import sqlite3
import hashlib
import secrets
from pydantic import BaseModel
import shutil
import time
import webbrowser
import threading

app = FastAPI(title="Telegram Clone")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Директории
BASE_DIR = Path(__file__).parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
PHOTOS_DIR = UPLOADS_DIR / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)
VIDEOS_DIR = UPLOADS_DIR / "videos"
VIDEOS_DIR.mkdir(exist_ok=True)
AUDIO_DIR = UPLOADS_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)
ROUNDS_DIR = UPLOADS_DIR / "rounds"
ROUNDS_DIR.mkdir(exist_ok=True)
DOCUMENTS_DIR = UPLOADS_DIR / "documents"
DOCUMENTS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR = BASE_DIR / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# База данных
def init_db():
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    
    # Users
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id TEXT PRIMARY KEY,
                  username TEXT UNIQUE,
                  password_hash TEXT,
                  created_at TIMESTAMP,
                  last_seen TIMESTAMP,
                  avatar_color TEXT)''')
    
    # Messages
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id TEXT PRIMARY KEY,
                  from_user TEXT,
                  to_user TEXT,
                  message TEXT,
                  type TEXT DEFAULT 'text',
                  file_path TEXT,
                  file_name TEXT,
                  file_size INTEGER,
                  duration INTEGER,
                  transcription TEXT,
                  timestamp TIMESTAMP,
                  is_read BOOLEAN DEFAULT 0,
                  reply_to TEXT,
                  FOREIGN KEY (from_user) REFERENCES users(id),
                  FOREIGN KEY (to_user) REFERENCES users(id))''')
    
    # Sessions
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (token TEXT PRIMARY KEY,
                  user_id TEXT,
                  device_info TEXT,
                  created_at TIMESTAMP,
                  last_activity TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    
    conn.commit()
    conn.close()

init_db()

class Database:
    @staticmethod
    def get_connection():
        return sqlite3.connect('messenger.db')
    
    @staticmethod
    def create_user(username: str, password: str) -> str:
        conn = Database.get_connection()
        c = conn.cursor()
        user_id = str(uuid.uuid4())[:8]
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        colors = ['#ff7b7b', '#7b9eff', '#7bff9e', '#ff7be6', '#ffd57b']
        color = secrets.choice(colors)
        
        try:
            c.execute("INSERT INTO users (id, username, password_hash, created_at, last_seen, avatar_color) VALUES (?, ?, ?, ?, ?, ?)",
                     (user_id, username, password_hash, datetime.now(), datetime.now(), color))
            conn.commit()
            return user_id
        except:
            return None
        finally:
            conn.close()
    
    @staticmethod
    def verify_user(username: str, password: str) -> Optional[str]:
        conn = Database.get_connection()
        c = conn.cursor()
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("SELECT id FROM users WHERE username = ? AND password_hash = ?", (username, pwd_hash))
        res = c.fetchone()
        conn.close()
        return res[0] if res else None
    
    @staticmethod
    def get_user(user_id: str) -> Optional[dict]:
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, username, avatar_color, last_seen FROM users WHERE id = ?", (user_id,))
        res = c.fetchone()
        conn.close()
        if res:
            return {"id": res[0], "username": res[1], "avatar_color": res[2], "last_seen": res[3]}
        return None
    
    @staticmethod
    def get_all_users():
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, username, avatar_color, last_seen FROM users ORDER BY username")
        users = [{"id": r[0], "username": r[1], "avatar_color": r[2], "last_seen": r[3]} for r in c.fetchall()]
        conn.close()
        return users
    
    @staticmethod
    def save_message(from_user: str, to_user: str, message: str, msg_type: str = 'text',
                     file_path: str = None, file_name: str = None, file_size: int = None,
                     duration: int = None, transcription: str = None, reply_to: str = None) -> str:
        conn = Database.get_connection()
        c = conn.cursor()
        msg_id = str(uuid.uuid4())[:8]
        ts = datetime.now()
        
        c.execute("""
            INSERT INTO messages 
            (id, from_user, to_user, message, type, file_path, file_name, file_size, duration, transcription, timestamp, is_read, reply_to) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, from_user, to_user, message, msg_type, file_path, file_name,
              file_size, duration, transcription, ts, False, reply_to))
        conn.commit()
        conn.close()
        return msg_id
    
    @staticmethod
    def get_messages(user1: str, user2: str, limit: int = 50):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT id, from_user, to_user, message, type, file_path, file_name,
                   file_size, duration, transcription, timestamp, is_read, reply_to
            FROM messages 
            WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)
            ORDER BY timestamp ASC
        """, (user1, user2, user2, user1))
        
        msgs = []
        for r in c.fetchall():
            msgs.append({
                "id": r[0], "from_user": r[1], "to_user": r[2], "message": r[3],
                "type": r[4], "file_path": r[5], "file_name": r[6], "file_size": r[7],
                "duration": r[8], "transcription": r[9], "timestamp": r[10],
                "is_read": bool(r[11]), "reply_to": r[12]
            })
        conn.close()
        return msgs
    
    @staticmethod
    def get_unread_count(user_id: str, from_user: str) -> int:
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM messages 
            WHERE from_user = ? AND to_user = ? AND is_read = 0
        """, (from_user, user_id))
        count = c.fetchone()[0]
        conn.close()
        return count
    
    @staticmethod
    def create_session(user_id: str, device_info: str) -> str:
        conn = Database.get_connection()
        c = conn.cursor()
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions (token, user_id, device_info, created_at, last_activity) VALUES (?, ?, ?, ?, ?)",
                 (token, user_id, device_info, datetime.now(), datetime.now()))
        conn.commit()
        conn.close()
        return token
    
    @staticmethod
    def verify_session(token: str) -> Optional[str]:
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        res = c.fetchone()
        if res:
            c.execute("UPDATE sessions SET last_activity = ? WHERE token = ?", (datetime.now(), token))
            conn.commit()
        conn.close()
        return res[0] if res else None
    
    @staticmethod
    def mark_as_read(message_id: str):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()
    
    @staticmethod
    def mark_all_as_read(user_id: str, from_user: str):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("""
            UPDATE messages SET is_read = 1 
            WHERE from_user = ? AND to_user = ? AND is_read = 0
        """, (from_user, user_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_last_seen(user_id: str):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET last_seen = ? WHERE id = ?", (datetime.now(), user_id))
        conn.commit()
        conn.close()

# Модели
class LoginRequest(BaseModel):
    username: str
    password: str

class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, Dict[str, WebSocket]] = {}
        self.status: Dict[str, bool] = {}
        self.last_ping: Dict[str, datetime] = {}
    
    async def connect(self, ws: WebSocket, user_id: str, device: str):
        await ws.accept()
        if user_id not in self.active:
            self.active[user_id] = {}
        self.active[user_id][device] = ws
        self.status[user_id] = True
        self.last_ping[user_id] = datetime.now()
        await self.broadcast_status(user_id, True)
    
    def disconnect(self, user_id: str, device: str):
        if user_id in self.active:
            if device in self.active[user_id]:
                del self.active[user_id][device]
            if not self.active[user_id]:
                del self.active[user_id]
                was_online = self.status.get(user_id, False)
                self.status[user_id] = False
                if was_online:
                    asyncio.create_task(self.broadcast_status(user_id, False))
    
    async def ping(self, user_id: str):
        self.last_ping[user_id] = datetime.now()
        self.status[user_id] = True
    
    async def check_offline(self):
        while True:
            await asyncio.sleep(10)
            now = datetime.now()
            for user_id, last in list(self.last_ping.items()):
                if (now - last) > timedelta(seconds=15):
                    if user_id in self.status and self.status[user_id]:
                        self.status[user_id] = False
                        await self.broadcast_status(user_id, False)
    
    async def send(self, from_user: str, to_user: str, data: dict):
        # Отправка получателю
        if to_user in self.active:
            for ws in self.active[to_user].values():
                try:
                    await ws.send_json(data)
                except:
                    pass
        
        # Отправка отправителю
        if from_user in self.active:
            for ws in self.active[from_user].values():
                try:
                    await ws.send_json({**data, "type": "my_" + data["type"]})
                except:
                    pass
    
    async def broadcast_status(self, user_id: str, online: bool):
        for uid, devices in self.active.items():
            if uid != user_id:
                for ws in devices.values():
                    try:
                        await ws.send_json({
                            "type": "user_status",
                            "user_id": user_id,
                            "online": online
                        })
                    except:
                        pass
    
    async def send_typing(self, from_user: str, to_user: str, typing: bool):
        if to_user in self.active:
            for ws in self.active[to_user].values():
                try:
                    await ws.send_json({
                        "type": "typing",
                        "from_user": from_user,
                        "typing": typing
                    })
                except:
                        pass
    
    async def send_read(self, from_user: str, to_user: str, message_id: str):
        if to_user in self.active:
            for ws in self.active[to_user].values():
                try:
                    await ws.send_json({
                        "type": "read",
                        "from_user": from_user,
                        "message_id": message_id
                    })
                except:
                    pass

manager = ConnectionManager()

# Запускаем проверку офлайн
@app.on_event("startup")
async def startup():
    asyncio.create_task(manager.check_offline())

# API
@app.post("/register")
async def register(req: LoginRequest):
    user_id = Database.create_user(req.username, req.password)
    if user_id:
        return {"ok": True}
    raise HTTPException(400, "Username exists")

@app.post("/login")
async def login(req: LoginRequest):
    user_id = Database.verify_user(req.username, req.password)
    if user_id:
        token = Database.create_session(user_id, "web")
        return {"token": token, "user_id": user_id}
    raise HTTPException(401, "Invalid credentials")

@app.get("/user/me")
async def get_me(request: Request):
    auth = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = Database.verify_session(auth)
    if not user_id:
        raise HTTPException(401)
    user = Database.get_user(user_id)
    if user:
        user["online"] = manager.status.get(user_id, False)
        return user
    raise HTTPException(404)

@app.get("/users")
async def get_users(request: Request):
    auth = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = Database.verify_session(auth)
    if not user_id:
        raise HTTPException(401)
    users = Database.get_all_users()
    result = []
    for u in users:
        if u["id"] != user_id:
            unread = Database.get_unread_count(user_id, u["id"])
            result.append({
                "id": u["id"],
                "username": u["username"],
                "avatar_color": u["avatar_color"],
                "online": manager.status.get(u["id"], False),
                "unread": unread
            })
    return result

@app.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    to_user: str = Form(...)
):
    auth = request.headers.get("Authorization", "").replace("Bearer ", "")
    from_user = Database.verify_session(auth)
    if not from_user:
        raise HTTPException(401)
    
    # Определяем тип
    content_type = file.content_type or ""
    ext = os.path.splitext(file.filename)[1].lower()
    
    if 'round' in file.filename.lower() or 'circle' in file.filename.lower():
        file_type = 'round'
        upload_dir = ROUNDS_DIR
    elif content_type.startswith('image/'):
        file_type = 'photo'
        upload_dir = PHOTOS_DIR
    elif content_type.startswith('video/'):
        file_type = 'video'
        upload_dir = VIDEOS_DIR
    elif content_type.startswith('audio/'):
        file_type = 'audio'
        upload_dir = AUDIO_DIR
    else:
        file_type = 'document'
        upload_dir = DOCUMENTS_DIR
    
    # Сохраняем
    file_id = str(uuid.uuid4())[:8]
    safe_name = f"{file_id}{ext}"
    file_path = upload_dir / safe_name
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Для аудио - примерная длительность
    duration = None
    transcription = None
    if file_type == 'audio':
        duration = 30  # Заглушка
        transcription = "Это транскрипция аудиосообщения..."  # Заглушка
    
    # Сохраняем в БД
    msg_id = Database.save_message(
        from_user=from_user,
        to_user=to_user,
        message="",
        msg_type=file_type,
        file_path=str(file_path.relative_to(BASE_DIR)),
        file_name=file.filename,
        file_size=len(content),
        duration=duration,
        transcription=transcription
    )
    
    # Отправляем через WS
    sender = Database.get_user(from_user)
    msg_data = {
        "id": msg_id,
        "from_user": from_user,
        "from_username": sender["username"],
        "to_user": to_user,
        "type": file_type,
        "file_path": str(file_path),
        "file_name": file.filename,
        "file_size": len(content),
        "duration": duration,
        "transcription": transcription,
        "timestamp": datetime.now().isoformat(),
        "is_read": False
    }
    
    await manager.send(from_user, to_user, {"type": "message", "data": msg_data})
    return {"id": msg_id}

@app.get("/messages/{other_id}")
async def get_messages(other_id: str, request: Request):
    auth = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = Database.verify_session(auth)
    if not user_id:
        raise HTTPException(401)
    
    msgs = Database.get_messages(user_id, other_id)
    other = Database.get_user(other_id)
    
    # Отмечаем все как прочитанные
    Database.mark_all_as_read(user_id, other_id)
    
    return {
        "user": {
            "id": other["id"],
            "username": other["username"],
            "avatar_color": other["avatar_color"],
            "online": manager.status.get(other_id, False)
        },
        "messages": msgs
    }

@app.get("/file/{message_id}")
async def get_file(message_id: str):
    conn = Database.get_connection()
    c = conn.cursor()
    c.execute("SELECT file_path, file_name, type FROM messages WHERE id = ?", (message_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(404)
    
    file_path = BASE_DIR / row[0]
    if not file_path.exists():
        raise HTTPException(404)
    
    # Для всех файлов возвращаем с правильным MIME типом
    mime_type = mimetypes.guess_type(row[1])[0] or 'application/octet-stream'
    
    return FileResponse(
        path=file_path,
        filename=row[1],
        media_type=mime_type
    )

@app.websocket("/ws/{token}/{device}")
async def websocket_endpoint(ws: WebSocket, token: str, device: str):
    user_id = Database.verify_session(token)
    if not user_id:
        await ws.close()
        return
    
    await manager.connect(ws, user_id, device)
    
    try:
        while True:
            data = await ws.receive_json()
            
            if data.get('type') == 'ping':
                await manager.ping(user_id)
            
            elif data.get('type') == 'message':
                # Текстовое сообщение
                msg_id = Database.save_message(
                    from_user=user_id,
                    to_user=data['to'],
                    message=data['message']
                )
                
                sender = Database.get_user(user_id)
                msg_data = {
                    "id": msg_id,
                    "from_user": user_id,
                    "from_username": sender["username"],
                    "to_user": data['to'],
                    "message": data['message'],
                    "type": "text",
                    "timestamp": datetime.now().isoformat(),
                    "is_read": False
                }
                
                await manager.send(user_id, data['to'], {"type": "message", "data": msg_data})
            
            elif data.get('type') == 'typing':
                await manager.send_typing(user_id, data['to'], data.get('typing', True))
            
            elif data.get('type') == 'read':
                Database.mark_as_read(data['message_id'])
                
                # Уведомляем отправителя
                conn = Database.get_connection()
                c = conn.cursor()
                c.execute("SELECT from_user FROM messages WHERE id = ?", (data['message_id'],))
                res = c.fetchone()
                conn.close()
                
                if res:
                    await manager.send_read(user_id, res[0], data['message_id'])
    
    except WebSocketDisconnect:
        manager.disconnect(user_id, device)
        Database.update_last_seen(user_id)

@app.get("/")
async def root(request: Request):
    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(x in ua for x in ['android', 'iphone', 'ipod', 'windows phone', 'mobile'])
    is_tablet = any(x in ua for x in ['ipad', 'tablet'])
    device = "mobile" if is_mobile else "tablet" if is_tablet else "desktop"
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "device": device
    })

def open_browser():
    """Открывает браузер через 2 секунды после запуска"""
    import time
    time.sleep(2)
    webbrowser.open("http://localhost:8000")

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                    TELEGRAM CLONE MESSENGER                   ║
    ╠═══════════════════════════════════════════════════════════════╣
    ║  • Поддержка всех типов файлов (PDF, Excel, Word и т.д.)     ║
    ║  • Идеальная мобильная версия                                ║
    ║  • Кружочки, аудио, видео, фото                              ║
    ║  • Статусы онлайн/офлайн/печатает/прочитано                  ║
    ║  • Счетчик непрочитанных сообщений                           ║
    ║                                                               ║
    ║  Сервер запущен: http://localhost:8000                        ║
    ║  Окно браузера откроется автоматически                        ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Запускаем браузер в отдельном потоке
    threading.Thread(target=open_browser, daemon=True).start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)