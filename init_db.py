from database import engine
from models import Base, User, UserRole
from auth import get_password_hash
from sqlalchemy.orm import Session

def init_database():
    print("Создаем таблицы в PostgreSQL...")
    Base.metadata.create_all(bind=engine)
    print("Таблицы успешно созданы!")
    
    db = Session(bind=engine)
    if not db.query(User).filter(User.login == "admin").first():
        admin = User(
            login="admin",
            password_hash=get_password_hash("admin123"),
            role=UserRole.OWNER 
        )
        db.add(admin)
        db.commit()
        print("Создан владелец: admin / admin123")
    else:
        print("Пользователь admin уже существует")
    db.close()

if __name__ == "__main__":
    init_database()