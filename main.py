from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os
import json

from database import get_db
from models import User, Board, BoardColumn, Card, Comment, AuditLog, UserRole
from auth import get_password_hash, verify_password, create_access_token, get_current_user, require_writer

app = FastAPI(title="Kanban API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserCreate(BaseModel):
    login: str
    password: str

class UserUpdateRole(BaseModel):
    role: str

class LoginRequest(BaseModel):
    login: str
    password: str

class BoardCreate(BaseModel):
    title: str

class BoardUpdate(BaseModel):
    title: str

class ColumnCreate(BaseModel):
    title: str
    position: int

class CardCreate(BaseModel):
    title: str
    column_id: int
    position: int
    priority: str = "medium"
    description: Optional[str] = None
    assignee: Optional[str] = None
    deadline: Optional[str] = None

class CardUpdate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None

class CardMove(BaseModel):
    column_id: int
    position: int

class CommentCreate(BaseModel):
    text: str


def log_action(db: Session, user_id: int, action: str, entity_type: str, entity_id: int, old_val=None, new_val=None):
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=json.dumps(old_val) if old_val else None,
        new_value=json.dumps(new_val) if new_val else None
    )
    db.add(log)



@app.get("/", response_class=HTMLResponse)
def root():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    return FileResponse(index_path)


@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.login == user.login).first():
        raise HTTPException(400, "Login already registered")
    
    new_user = User(
        login=user.login,
        password_hash=get_password_hash(user.password),
        role=UserRole.READER
    )
    db.add(new_user)
    db.commit()
    

    token = create_access_token({"sub": new_user.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": new_user.role.value,
        "user_id": new_user.id,
        "message": "User created"
    }

@app.post("/login")
def login(form: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.login == form.login).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "Incorrect login or password")
    token = create_access_token({"sub": user.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role.value,
        "user_id": user.id
    }


@app.get("/users")
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    users = db.query(User).all()
    return [{"id": u.id, "login": u.login, "role": u.role.value} for u in users]

@app.put("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    role_data: UserUpdateRole,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.OWNER:
        raise HTTPException(403, "Only owners can change user roles")
    
    valid_roles = [r.value for r in UserRole]
    if role_data.role not in valid_roles:
        raise HTTPException(400, f"Invalid role. Must be one of: {valid_roles}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    old_role = user.role.value
    user.role = UserRole(role_data.role)
    
    log_action(db, current_user.id, "UPDATE", "UserRole", user_id, 
               old_val={"role": old_role}, new_val={"role": role_data.role})
    db.commit()
    
    return {"message": "Role updated", "user_id": user_id, "new_role": role_data.role}


@app.get("/boards")
def get_boards(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Board).all()

@app.post("/boards")
def create_board(board: BoardCreate, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    new_board = Board(title=board.title, owner_id=user.id)
    db.add(new_board)

    db.flush()
    
    for pos, title in enumerate(["Сделать", "В процессе", "На проверке", "Готово"]):
        db.add(BoardColumn(board_id=new_board.id, title=title, position=pos))
    
    db.commit()
    db.refresh(new_board)
    log_action(db, user.id, "CREATE", "Board", new_board.id, new_val={"title": new_board.title})
    db.commit()
    return new_board

@app.put("/boards/{board_id}")
def update_board(board_id: int, board: BoardUpdate, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    db_board = db.query(Board).filter(Board.id == board_id).first()
    if not db_board:
        raise HTTPException(404, "Board not found")
    old_val = {"title": db_board.title}
    db_board.title = board.title
    
    log_action(db, user.id, "UPDATE", "Board", board_id, old_val=old_val, new_val={"title": board.title})
    db.commit()
    return db_board

@app.delete("/boards/{board_id}")
def delete_board(board_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    board = db.query(Board).filter(Board.id == board_id).first()
    if not board:
        raise HTTPException(404, "Board not found")
    
    log_action(db, user.id, "DELETE", "Board", board_id)
    db.delete(board)
    db.commit()
    return {"message": "Board deleted"}

@app.get("/boards/{board_id}/columns")
def get_columns(board_id: int, db: Session = Depends(get_db)):
    return db.query(BoardColumn).filter(BoardColumn.board_id == board_id).order_by(BoardColumn.position).all()

@app.delete("/columns/{column_id}")
def delete_column(column_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    col = db.query(BoardColumn).filter(BoardColumn.id == column_id).first()
    if not col:
        raise HTTPException(404, "Column not found")
    
    log_action(db, user.id, "DELETE", "Column", column_id)
    db.delete(col)
    db.commit()
    return {"message": "Column deleted"}

@app.get("/boards/{board_id}/cards")
def get_cards(board_id: int, db: Session = Depends(get_db)):
    query = text("""
        SELECT c.id, c.title, c.description, c.priority, c.assignee, c.deadline, c.position, c.column_id
        FROM cards c
        JOIN columns col ON c.column_id = col.id
        WHERE col.board_id = :board_id
        ORDER BY col.position, c.position
    """)
    result = db.execute(query, {"board_id": board_id}).fetchall()
    return [dict(row._mapping) for row in result]

@app.post("/cards")
def create_card(card: CardCreate, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    deadline_dt = None
    if card.deadline:
        try:
            deadline_dt = datetime.fromisoformat(card.deadline)
        except:
            pass
    
    new_card = Card(
        title=card.title, description=card.description, priority=card.priority,
        assignee=card.assignee, deadline=deadline_dt, column_id=card.column_id, position=card.position
    )
    db.add(new_card)
    db.commit()
    db.refresh(new_card)
    
    log_action(db, user.id, "CREATE", "Card", new_card.id, new_val={"title": new_card.title})
    db.commit()
    return new_card

@app.put("/cards/{card_id}")
def update_card(card_id: int, card: CardUpdate, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    db_card = db.query(Card).filter(Card.id == card_id).first()
    if not db_card:
        raise HTTPException(404, "Card not found")
    
    old_val = {"title": db_card.title, "priority": db_card.priority}
    db_card.title = card.title
    db_card.description = card.description
    db_card.priority = card.priority
    db_card.assignee = card.assignee
    if card.deadline:
        try:
            db_card.deadline = datetime.fromisoformat(card.deadline)
        except:
            pass
            
    log_action(db, user.id, "UPDATE", "Card", card_id, old_val=old_val, new_val={"title": db_card.title})
    db.commit()
    db.refresh(db_card)
    return db_card

@app.put("/cards/{card_id}/move")
def move_card(card_id: int, move: CardMove, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(404, "Card not found")
    old_data = {"column_id": card.column_id, "position": card.position}
    card.column_id = move.column_id
    card.position = move.position
    
    log_action(db, user.id, "UPDATE", "Card", card_id, old_val=old_data, new_val={"column_id": move.column_id, "position": move.position})
    db.commit()
    return {"message": "Card moved"}

@app.delete("/cards/{card_id}")
def delete_card(card_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(404, "Card not found")
    
    log_action(db, user.id, "DELETE", "Card", card_id)
    db.delete(card)
    db.commit()
    return {"message": "Card deleted"}

@app.post("/cards/{card_id}/comments")
def add_comment(card_id: int, comment: CommentCreate, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    new_comment = Comment(card_id=card_id, user_id=user.id, text=comment.text)
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment) 
    
    log_action(db, user.id, "CREATE", "Comment", new_comment.id, new_val={"text": comment.text})
    db.commit()
    return {"message": "Comment added"}

@app.get("/cards/{card_id}/comments")
def get_comments(card_id: int, db: Session = Depends(get_db)):
    return db.query(Comment).filter(Comment.card_id == card_id).order_by(Comment.created_at).all()

@app.get("/audit-log")
def get_audit_log(
    user_id: Optional[int] = Query(None),
    board_id: Optional[int] = Query(None),
    card_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(AuditLog)
    if user_id is not None: 
        query = query.filter(AuditLog.user_id == user_id)
    if board_id is not None: 
        query = query.filter(AuditLog.entity_type == "Board", AuditLog.entity_id == board_id)
    if card_id is not None: 
        query = query.filter(AuditLog.entity_type == "Card", AuditLog.entity_id == card_id)
    if action is not None: 
        query = query.filter(AuditLog.action == action)
    
    results = query.order_by(AuditLog.timestamp.desc()).limit(100).all()
    
    return [
        {
            "id": log.id, 
            "user_id": log.user_id,
            "user_login": log.user.login if log.user else f"User_{log.user_id}",
            "action": log.action, 
            "entity_type": log.entity_type, 
            "entity_id": log.entity_id,
            "old_value": log.old_value, 
            "new_value": log.new_value,
            "timestamp": log.timestamp.isoformat()
        } for log in results
    ]

@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    query = text("SELECT c.priority, COUNT(c.id) as card_count FROM cards c GROUP BY c.priority")
    result = db.execute(query).fetchall()
    return [dict(row._mapping) for row in result]