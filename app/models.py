from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

class LotteryDraw(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draw_number = db.Column(db.String(20), unique=True, nullable=False)
    draw_date = db.Column(db.Date, nullable=False)
    numbers = db.Column(db.String(30), nullable=False)  # Format: "01,02,03,04,05+06,07"
    prize_pool = db.Column(db.Float)
    first_prize_num = db.Column(db.Integer)
    first_prize_amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserPrediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    numbers = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    draw_number = db.Column(db.String(20))  # 对应的开奖期号
    is_hit = db.Column(db.Boolean, default=False)  # 是否中奖
    prize_amount = db.Column(db.Float, default=0)  # 中奖金额

class ManualImportData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draw_number = db.Column(db.String(20), unique=True, nullable=False)  # 期号
    front_hot_numbers = db.Column(db.String(50), nullable=False)  # 前区7个热门数字，用逗号分隔
    next_front_numbers = db.Column(db.String(50), nullable=False)  # 后一期中奖数字前区数字，用逗号分隔
    back_hot_numbers = db.Column(db.String(50), nullable=False)  # 后区热门4个数字，用逗号分隔
    next_back_numbers = db.Column(db.String(50), nullable=False)  # 后一期中奖数字后区数字，用逗号分隔
    front_cold_numbers = db.Column(db.String(50), nullable=False)  # 前区7个冷门数字，用逗号分隔
    back_cold_numbers = db.Column(db.String(50), nullable=False)  # 后区冷门4个数字，用逗号分隔
    created_at = db.Column(db.DateTime, default=datetime.utcnow) 