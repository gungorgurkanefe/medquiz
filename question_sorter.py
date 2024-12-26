import re
from flask_sqlalchemy import SQLAlchemy

db = None
Question = None

def init_db(database, question_model):
    """Veritabanı ve Question modelini başlatır"""
    global db, Question
    db = database
    Question = question_model

def extract_number_from_text(text):
    """Soru metninin başındaki sayıyı çıkarır"""
    match = re.match(r'(\d+)\.', text)
    if match:
        return int(match.group(1))
    return 0

def sort_questions_by_number():
    """Soruları başındaki numaraya göre sıralar ve question_number'ı günceller"""
    try:
        # Tüm soruları al
        questions = Question.query.all()
        
        # Her kategori için ayrı sıralama yap
        categories = {}
        for q in questions:
            key = (q.class_year, q.committee, q.exam_number)
            if key not in categories:
                categories[key] = []
            categories[key].append(q)
        
        # Her kategoriyi kendi içinde sırala
        for category_questions in categories.values():
            # Soruları metindeki numaraya göre sırala
            sorted_questions = sorted(category_questions, key=lambda x: extract_number_from_text(x.question_text))
            
            # Yeni sıra numaralarını ata
            for index, question in enumerate(sorted_questions, start=1):
                question.question_number = index
        
        # Değişiklikleri kaydet
        db.session.commit()
        return True
    except Exception as e:
        print(f"Sıralama sırasında hata oluştu: {str(e)}")
        db.session.rollback()
        return False

def update_question_numbers():
    """Yeni soru eklendiğinde sıralamayı günceller"""
    return sort_questions_by_number() 