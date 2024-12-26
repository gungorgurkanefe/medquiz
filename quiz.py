from flask import Blueprint, render_template, request, jsonify
from app import db, Question
import random

quiz_bp = Blueprint('quiz', __name__)

@quiz_bp.route('/quiz')
def quiz():
    # Sınıf ve komite bilgilerini hazırla
    class_committees = {
        1: list(range(1, 6)),  # 1. dönem: 5 komite
        2: list(range(1, 6)),  # 2. dönem: 5 komite
        3: list(range(1, 7))   # 3. dönem: 6 komite
    }
    
    return render_template('quiz.html', class_committees=class_committees)

@quiz_bp.route('/start_quiz')
def start_quiz():
    class_year = request.args.get('class_year', type=int)
    committee = request.args.get('committee', type=int)
    exam_number = request.args.get('exam_number', type=int)
    question_count = request.args.get('question_count', default=10, type=int)
    
    if not all([class_year, committee, exam_number]):
        return jsonify({'error': 'Lütfen tüm kategorileri seçin.'}), 400
    
    # Seçilen kriterlere göre soruları filtrele
    questions = Question.query.filter_by(
        class_year=class_year,
        committee=committee,
        exam_number=exam_number
    ).all()
    
    if not questions:
        return jsonify({'error': 'Seçilen kriterlere uygun soru bulunamadı.'}), 404
    
    # Rastgele soru seç
    selected_questions = random.sample(questions, min(question_count, len(questions)))
    
    # Sınav oturumu için soruları hazırla
    quiz_questions = []
    for q in selected_questions:
        quiz_questions.append({
            'id': q.id,
            'text': q.question_text,
            'question_number': q.question_number
        })
    
    return render_template('quiz_questions.html',
                         questions=quiz_questions,
                         class_year=class_year,
                         committee=committee,
                         exam_number=exam_number)

@quiz_bp.route('/check_quiz_answer', methods=['POST'])
def check_quiz_answer():
    try:
        data = request.get_json()
        question_id = data.get('question_id')
        selected_answer = data.get('answer')
        
        if not question_id or not selected_answer:
            return jsonify({'error': 'Eksik bilgi'}), 400
            
        question = Question.query.get(question_id)
        
        if not question:
            return jsonify({'error': 'Soru bulunamadı'}), 404
            
        is_correct = selected_answer.upper() == question.correct_answer.upper()
        
        return jsonify({
            'success': True,
            'is_correct': is_correct
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@quiz_bp.route('/quiz_result', methods=['POST'])
def quiz_result():
    try:
        data = request.get_json()
        answers = data.get('answers', [])
        total_questions = len(answers)
        correct_answers = sum(1 for ans in answers if ans.get('is_correct', False))
        
        success_rate = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
        
        return render_template('quiz_result.html',
                             total_questions=total_questions,
                             correct_answers=correct_answers,
                             success_rate=success_rate)
                             
    except Exception as e:
        return jsonify({'error': str(e)}), 500 