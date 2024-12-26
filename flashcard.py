from flask import Blueprint, render_template, request, jsonify
import sqlite3
import random
import os

flashcard_bp = Blueprint('flashcard', __name__)

def init_db():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'questions.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS questions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  question_text TEXT NOT NULL,
                  option_a TEXT NOT NULL,
                  option_b TEXT NOT NULL,
                  option_c TEXT NOT NULL,
                  option_d TEXT NOT NULL,
                  option_e TEXT NOT NULL,
                  correct_answer TEXT NOT NULL,
                  class_year INTEGER NOT NULL,
                  committee INTEGER NOT NULL,
                  exam_number INTEGER NOT NULL,
                  question_number INTEGER NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    return db_path

def get_db_connection():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'questions.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    init_db()  # Veritabanı ve tabloyu oluştur
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@flashcard_bp.route('/flashcards')
def flashcards():
    class_year = request.args.get('class_year', type=int)
    committee = request.args.get('committee', type=int)
    exam_number = request.args.get('exam_number', type=int)
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Temel sorgu
    query = "SELECT * FROM questions"
    params = []
    
    # Filtre koşullarını oluştur
    conditions = []
    if class_year:
        conditions.append("class_year = ?")
        params.append(class_year)
    if committee:
        conditions.append("committee = ?")
        params.append(committee)
    if exam_number:
        conditions.append("exam_number = ?")
        params.append(exam_number)
    
    # Koşulları sorguya ekle
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    # Soruları rastgele sırala
    query += " ORDER BY RANDOM()"
    
    c.execute(query, params)
    questions = c.fetchall()
    
    # Sütun isimlerini al
    columns = [description[0] for description in c.description]
    
    # Soruları sözlük formatına dönüştür
    questions = [dict(zip(columns, q)) for q in questions]
    
    conn.close()
    
    # Sınıf ve komite bilgilerini hazırla
    class_committees = {
        1: list(range(1, 6)),  # 1. sınıf: 5 komite
        2: list(range(1, 6)),  # 2. sınıf: 5 komite
        3: list(range(1, 7))   # 3. sınıf: 6 komite
    }
    
    return render_template('flashcards.html', questions=questions, class_committees=class_committees)

@flashcard_bp.route('/check_flashcard_answer', methods=['POST'])
def check_flashcard_answer():
    try:
        data = request.json
        question_id = data.get('question_id')
        selected_answer = data.get('answer')
        
        if not question_id or not selected_answer:
            return jsonify({'error': 'Missing question_id or answer'}), 400
            
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT correct_answer FROM questions WHERE id = ?', (question_id,))
        result = c.fetchone()
        conn.close()
        
        if not result:
            return jsonify({'error': 'Question not found'}), 404
            
        correct_answer = result['correct_answer']
        is_correct = selected_answer.upper() == correct_answer.upper()
        
        return jsonify({
            'success': True,
            'is_correct': is_correct
        })
        
    except Exception as e:
        print(f"Hata oluştu: {str(e)}")
        return jsonify({'error': str(e)}), 500 