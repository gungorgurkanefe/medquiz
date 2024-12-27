from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, g
from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai
from pathlib import Path
import sqlite3
import time
from datetime import datetime
import os
from PIL import Image
import re
from werkzeug.utils import secure_filename
from question_validator import QuestionValidator
from flashcard import flashcard_bp
from sqlalchemy.sql import func

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Flash mesajları için gerekli

# Flashcard blueprint'ini kaydet
app.register_blueprint(flashcard_bp)

# Upload klasörü yapılandırması
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Veritabanı konfigürasyonu
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database', 'questions.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# SQLAlchemy instance'ı oluştur
db = SQLAlchemy(app)

# Question modeli
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.Text, nullable=False)
    correct_answer = db.Column(db.String(1), nullable=False)
    class_year = db.Column(db.Integer, nullable=False)
    committee = db.Column(db.Integer, nullable=False)
    exam_number = db.Column(db.Integer, nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Veritabanını oluştur
with app.app_context():
    db.create_all()

# Question Sorter'ı başlat
import question_sorter
question_sorter.init_db(db, Question)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Configure Gemini API
GEMINI_API_KEY = "AIzaSyDqbTC7P8NDuH9bkJZ2xtb6nodcE6UsEiE"
genai.configure(api_key=GEMINI_API_KEY)

# Initialize Gemini model with custom configuration
generation_config = genai.types.GenerationConfig(
    temperature=1.0,
    max_output_tokens=8192,  # Maksimum çıktı uzunluğunu artır
    top_p=1.0,
    top_k=40
)
model = genai.GenerativeModel('gemini-1.5-flash-002', generation_config=generation_config)

# Rate limiting variables
last_request_time = 0
requests_this_minute = 0

def init_db():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'questions.db')
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

# Global değişken olarak veritabanı yolunu sakla
DB_PATH = init_db()

# QuestionValidator örneğini oluştur
question_validator = QuestionValidator(DB_PATH)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def can_make_request():
    global last_request_time, requests_this_minute
    current_time = time.time()
    
    if current_time - last_request_time >= 60:
        requests_this_minute = 0
        last_request_time = current_time
    
    if requests_this_minute < 15:
        requests_this_minute += 1
        return True
    return False

def validate_and_format_question(question_text):
    # Debug bilgisi için
    debug_info = {
        'original_text': question_text,
        'options_count': 0,
        'has_number': False,
        'options': []
    }
    
    # Soru metnini temizle
    question_text = question_text.strip()
    
    # Soru numarası kontrolü
    match = re.match(r'(\d+)\.', question_text)
    if not match:
        print(f"Soru numarası bulunamadı: {question_text[:50]}...")
        return None
        
    question_number = int(match.group(1))
    debug_info['has_number'] = True
    
    # Şıkları bul - daha esnek bir regex kullanıyoruz
    options = []
    option_pattern = r'(?:^|\n)([A-E])[\)\.]\s*(.+?)(?=(?:\n[A-E][\)\.]\s*|\n\n|$))'
    option_matches = re.finditer(option_pattern, question_text, re.MULTILINE | re.DOTALL)
    
    for match in option_matches:
        option_letter = match.group(1)
        option_text = match.group(2).strip()
        options.append((option_letter, option_text))
        debug_info['options'].append(f"{option_letter}) {option_text}")
    
    debug_info['options_count'] = len(options)
    print(f"Soru {question_number} için şık sayısı: {len(options)}")
    
    # Şık sayısı kontrolü - sadece 5 şıkkı olan soruları kabul et
    if len(options) != 5:
        print(f"Soru {question_number} {len(options)} şık içerdiği için geçersiz sayıldı")
        return None
    
    # Soru metnini al (şıkları çıkararak)
    question_parts = re.split(r'\n[A-E][\)\.]\s*', question_text)
    question_text = question_parts[0].strip()
    
    # Şıkları formatla
    formatted_options = [f"{letter}) {text}" for letter, text in sorted(options)]
    
    formatted_question = question_text + '\n\n' + '\n'.join(formatted_options)
    print(f"Soru {question_number} formatlandı")
    return formatted_question

def extract_questions(text):
    # Soruları ve şıkları bul
    questions = []
    current_question = None
    current_options = []
    question_text_buffer = []
    current_question_number = None
    
    lines = text.split('\n')
    in_question = False
    in_options = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Yeni soru başlangıcı
        if re.match(r'^\d+\.', line):
            # Önceki soruyu kaydet
            if current_question and current_options:
                # Şıkların tam olarak 5 tane olduğunu kontrol et
                if len(current_options) == 5:
                    # Her şıkkın doğru formatta olduğunu kontrol et
                    valid_options = True
                    expected_letters = ['A)', 'B)', 'C)', 'D)', 'E)']
                    
                    for i, opt in enumerate(current_options):
                        # Şık harfini ve içeriğini kontrol et
                        if not opt.startswith(expected_letters[i]):
                            print(f"Hatalı şık formatı: {opt}")
                            valid_options = False
                            break
                            
                        # Şık içeriğinin yeterli uzunlukta olduğunu kontrol et
                        content = opt.split(')', 1)[1].strip()
                        if len(content) < 2:  # Minimum uzunluğu 2'ye düşürdük çünkü "No" gibi kısa ama geçerli cevaplar olabilir
                            print(f"Şık içeriği çok kısa: {opt}")
                            valid_options = False
                            break
                            
                        # Şıkkın tam olduğunu kontrol et (yarım kalmamış olmalı)
                        if content.endswith('...') or content.endswith('…'):
                            print(f"Yarım kalmış şık: {opt}")
                            valid_options = False
                            break
                            
                        # "not visible" veya "undefined" gibi API hata mesajlarını kontrol et
                        if content.lower() in ['undefined', 'not visible']:
                            print(f"Geçersiz şık içeriği: {opt}")
                            valid_options = False
                            break
                    
                    if valid_options:
                        full_question = {
                            'text': current_question + '\n\n' + '\n'.join(current_options),
                            'number': current_question_number
                        }
                        questions.append(full_question)
                        print(f"Soru eklendi: {current_question[:100]}...")
                    else:
                        print(f"Soru atlandı (geçersiz şık formatı): {current_question[:100]}...")
                else:
                    print(f"Soru atlandı (şık sayısı {len(current_options)}): {current_question[:100]}...")
            
            # Soru numarasını al
            match = re.match(r'^(\d+)\.', line)
            current_question_number = int(match.group(1))
            current_question = line
            question_text_buffer = [line]
            current_options = []
            in_question = True
            in_options = False
            print(f"\nYeni soru bulundu: {line}")
            continue
            
        # Şık satırı
        option_match = re.match(r'^([A-E])[\)\.]\s*(.+)$', line)
        if option_match:
            if in_question:
                current_question = ' '.join(question_text_buffer)
                in_question = False
            in_options = True
            
            option_letter = option_match.group(1)
            option_text = option_match.group(2).strip()
            
            # Şıkların sıralı gelmesini kontrol et
            expected_index = len(current_options)
            expected_letter = chr(65 + expected_index)  # A:0, B:1, C:2, D:3, E:4
            
            if option_letter == expected_letter and option_text:
                current_options.append(f"{option_letter}) {option_text}")
                print(f"Şık eklendi: {option_letter}) {option_text}")
            else:
                print(f"Şık sırası hatalı veya içerik eksik: Beklenen {expected_letter}, Gelen {option_letter}")
                current_options = []
                in_options = False
                
        elif in_question:
            question_text_buffer.append(line)
        elif in_options and line:
            current_options[-1] = current_options[-1] + ' ' + line
    
    # Son soruyu kontrol et ve ekle
    if current_question and current_options:
        if len(current_options) == 5:
            valid_options = True
            expected_letters = ['A)', 'B)', 'C)', 'D)', 'E)']
            
            for i, opt in enumerate(current_options):
                if not opt.startswith(expected_letters[i]):
                    print(f"Hatalı şık formatı: {opt}")
                    valid_options = False
                    break
                    
                content = opt.split(')', 1)[1].strip()
                if len(content) < 2:
                    print(f"Şık içeriği çok kısa: {opt}")
                    valid_options = False
                    break
                    
                if content.endswith('...') or content.endswith('…'):
                    print(f"Yarım kalmış şık: {opt}")
                    valid_options = False
                    break
                    
                if content.lower() in ['undefined', 'not visible']:
                    print(f"Geçersiz şık içeriği: {opt}")
                    valid_options = False
                    break
            
            if valid_options:
                full_question = {
                    'text': current_question + '\n\n' + '\n'.join(current_options),
                    'number': current_question_number
                }
                questions.append(full_question)
                print(f"Son soru eklendi: {current_question[:100]}...")
            else:
                print(f"Son soru atlandı (geçersiz şık formatı): {current_question[:100]}...")
        else:
            print(f"Son soru atlandı (şık sayısı {len(current_options)}): {current_question[:100]}...")
    
    print(f"\nToplam {len(questions)} soru işlendi")
    return questions

def clean_and_format_text(text):
    # Başlangıç ve son kısımdaki gereksiz metinleri temizle
    text = re.sub(r'^.*?(?=\d+\.)', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'Doğru Şık.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'Correct answer.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'Answer:.*$', '', text, flags=re.MULTILINE)
    
    # Gereksiz boşlukları temizle
    text = re.sub(r'\s*\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    
    # Soruları ayır ve validate et
    questions = extract_questions(text)
    
    if not questions:
        return ""
        
    # Soruları birleştir
    return '\n\n'.join(questions)

def check_similar_questions(question_text):
    """Veritabanında benzer soru olup olmadığını kontrol eder"""
    try:
        # Soru metnini küçük harfe çevir ve gereksiz boşlukları temizle
        question_text = ' '.join(question_text.lower().split())
        
        # Veritabanındaki tüm soruları al
        existing_questions = Question.query.all()
        
        for existing in existing_questions:
            # Mevcut soruyu da aynı şekilde temizle
            existing_text = ' '.join(existing.question_text.lower().split())
            
            # Metinlerin benzerliğini kontrol et
            if existing_text == question_text:
                return True
                
        return False
    except Exception as e:
        print(f"Benzer soru kontrolünde hata: {str(e)}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'files[]' not in request.files:
            return jsonify({'error': 'Dosya seçilmedi'}), 400
        
        files = request.files.getlist('files[]')
        class_year = request.form.get('class_year', type=int)
        committee = request.form.get('committee', type=int)
        exam_number = request.form.get('exam_number', type=int)
        
        if not files:
            return jsonify({'error': 'Dosya seçilmedi'}), 400
        
        if not class_year or not committee or not exam_number:
            return jsonify({'error': 'Lütfen sınıf, komite ve sınav numarası seçin'}), 400
        
        all_questions = []
        
        for file in files:
            if file.filename == '':
                continue
                
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(image_path)
                
                try:
                    # Resmi aç ve Gemini API için hazırla
                    img = Image.open(image_path)
                    
                    # Gemini API'den metin çıkarma...
                    response = model.generate_content([
                        """Your task is to extract and transcribe medical questions from the image.
                        
                        Important Rules:
                        1. Start reading from the question number (e.g., "1.", "2.", etc.)
                        2. Include the COMPLETE question text, including any case descriptions, scenarios, and premises/statements
                        3. If there are numbered statements (I, II, III, etc.) or premises before the question, include them as part of the question text
                        4. Extract ALL questions that are fully visible in the image
                        5. Keep the original language, DO NOT translate
                        6. Include all options (A through E) for each question
                        7. Only include questions that have ALL five options (A,B,C,D,E) visible
                        8. Do not add any additional text, comments, or explanations
                        9. Do not indicate correct answers
                        10. Format each question exactly as it appears, preserving line breaks and numbered statements
                        11. If a question is cut off or partially visible, skip it entirely
                        12. If a question does not have an option, do not take that question
                        13. If all options A-B-C-D-E are not visible, DO NOT WRITE THE QUESTION. ALWAYS OBEY THE THAT RULE !IMPORTANT!
                        14. If one of the options is lack, do NOT WRITE THE QUESTION !IMPORTANT!
                        15. For questions with numbered statements/premises:
                            - Include all numbered statements (I, II, III, etc.) before the actual question
                            - Keep the original formatting and numbering of statements
                            - Ensure all statements are complete and visible

                        16. If the last option (E) is not visible, do NOT WRITE THE QUESTION. Don't Write The Option As "None" !IMPORTANT!
                        17. ALWAYS OBEY THE 16TH RULE. 
                        
                        
                        Output Format:
                        [Question Number]. [Numbered Statements/Premises if any]
                        [Complete Question Text]
                        A) [Option A Text]
                        B) [Option B Text]
                        C) [Option C Text]
                        D) [Option D Text]
                        E) [Option E Text]
                        
                        [blank line between questions]""",
                        img
                    ])
                    
                    # Metni temizle ve biçimlendir
                    questions = extract_questions(response.text)
                    if questions:
                        all_questions.extend(questions)
                    
                except Exception as e:
                    print(f"Hata oluştu: {str(e)}")
                    return jsonify({'error': str(e)}), 500
                
                finally:
                    # Geçici dosyayı temizle
                    if os.path.exists(image_path):
                        os.remove(image_path)
        
        if not all_questions:
            return jsonify({'error': 'Fotoğraflarda geçerli soru bulunamadı'}), 400
        
        return jsonify({
            'success': True,
            'questions': all_questions
        })
    
    # Sınıf ve komite bilgilerini hazırla
    class_committees = {
        1: list(range(1, 6)),  # 1. sınıf: 5 komite
        2: list(range(1, 6)),  # 2. sınıf: 5 komite
        3: list(range(1, 7))   # 3. sınıf: 6 komite
    }
    
    return render_template('upload.html', class_committees=class_committees)

@app.route('/save_questions', methods=['POST'])
def save_questions():
    try:
        data = request.json
        questions = data.get('questions', [])
        answers = data.get('answers', [])
        class_year = int(data.get('class_year', 0))
        committee = int(data.get('committee', 0))
        exam_number = int(data.get('exam_number', 0))
        
        if not questions or not answers or not class_year or not committee or not exam_number:
            return jsonify({'error': 'Eksik veri'}), 400
            
        if len(questions) != len(answers):
            return jsonify({'error': 'Soru ve cevap sayısı eşleşmiyor'}), 400
        
        # Soruları kontrol et
        duplicate_questions = []
        new_questions = []
        new_answers = []
        processed_questions = set()  # İşlenmiş soruları tutacak set
        
        for i, (question, answer) in enumerate(zip(questions, answers)):
            question_text = question['text']
            question_number = question['number']
            
            parts = question_text.split('\n\n')
            if len(parts) >= 2:
                question_text = parts[0].strip()
                
                # Veritabanındaki benzer soruları kontrol et
                is_duplicate, similar_id, similarity = question_validator.is_duplicate_question(
                    question_text, class_year, committee
                )
                
                if is_duplicate:
                    duplicate_questions.append({
                        'question': question_text,
                        'similar_id': similar_id,
                        'similarity': similarity,
                        'reason': 'Veritabanında benzer soru bulundu'
                    })
                    continue
                
                # Yeni yüklenen sorular arasında benzerlik kontrolü
                is_duplicate_in_new = False
                for j, processed_q in enumerate(new_questions):
                    processed_text = processed_q[0]  # question_text
                    similarity = question_validator.calculate_similarity(processed_text, question_text)
                    
                    if similarity >= 0.8:  # Benzerlik eşik
                        duplicate_questions.append({
                            'question': question_text,
                            'similar_id': j + 1,  # Yeni sorulardaki indeks
                            'similarity': similarity,
                            'reason': 'Yüklenen sorular arasında benzer soru bulundu'
                        })
                        is_duplicate_in_new = True
                        break
                
                if not is_duplicate_in_new:
                    new_questions.append((question_text, parts[1], question_number))
                    new_answers.append(answer)
        
        # Yeni soruları kaydet
        conn = get_db_connection()
        c = conn.cursor()
        saved_count = 0
        
        for (question_text, options_text, question_number), answer in zip(new_questions, new_answers):
            options = {}
            for line in options_text.split('\n'):
                if line.strip():
                    option_match = re.match(r'^([A-E])\)(.*?)$', line.strip())
                    if option_match:
                        options[option_match.group(1)] = option_match.group(2).strip()
            
            if len(options) == 5:  # Sadece 5 şıkkı olan soruları kaydet
                c.execute('''INSERT INTO questions 
                            (question_text, option_a, option_b, option_c, option_d, option_e, 
                             correct_answer, class_year, committee, exam_number, question_number)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (question_text, options['A'], options['B'], options['C'], 
                         options['D'], options['E'], answer, class_year, committee, exam_number, question_number))
                saved_count += 1
        
        conn.commit()
        conn.close()

        # Sonuç mesajını hazırla
        message = f'{saved_count} yeni soru kaydedildi.'
        if duplicate_questions:
            message += f' {len(duplicate_questions)} soru benzerlik nedeniyle atlandı.'
        
        return jsonify({
            'success': True,
            'message': message,
            'duplicate_questions': duplicate_questions
        })
        
    except Exception as e:
        print(f"Hata oluştu: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/check_answer', methods=['POST'])
def check_answer():
    try:
        data = request.get_json()
        question_id = data.get('question_id')
        selected_answer = data.get('answer')
        
        if not question_id or not selected_answer:
            return jsonify({'error': 'Missing question_id or answer'}), 400
            
        # Soruyu veritabanından al
        question = Question.query.get(question_id)
        
        if not question:
            return jsonify({'error': 'Question not found'}), 404
            
        is_correct = selected_answer.upper() == question.correct_answer.upper()
        
        return jsonify({
            'success': True,
            'is_correct': is_correct,
            'correct_answer': question.correct_answer
        })
        
    except Exception as e:
        print(f"Hata oluştu: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/solve')
def solve():
    # Veritabanından tüm soruları al ve kategorilere göre grupla
    questions = Question.query.with_entities(
        Question.class_year,
        Question.committee,
        Question.exam_number,
        func.count().label('count')
    ).group_by(
        Question.class_year,
        Question.committee,
        Question.exam_number
    ).all()
    
    # Soru içeren kategorileri sakla
    active_categories = {}
    for q in questions:
        if q.class_year not in active_categories:
            active_categories[q.class_year] = {}
        if q.committee not in active_categories[q.class_year]:
            active_categories[q.class_year][q.committee] = []
        active_categories[q.class_year][q.committee].append(q.exam_number)
    
    # Sınıf ve komite bilgilerini hazırla (sadece aktif olanlar)
    class_committees = {}
    for class_year, committees in active_categories.items():
        class_committees[class_year] = {
            'committees': sorted(list(committees.keys())),  # Aktif komiteler
            'exams': {committee: sorted(exams) for committee, exams in committees.items()}  # Her komite için aktif sınavlar
        }
    
    return render_template('solve.html', class_committees=class_committees)

@app.route('/questions')
def questions():
    class_year = request.args.get('class_year', type=int)
    committee = request.args.get('committee', type=int)
    exam_number = request.args.get('exam_number', type=int)
    
    if not all([class_year, committee, exam_number]):
        flash('Lütfen tüm kategorileri seçin.', 'error')
        return redirect(url_for('solve'))
    
    # Soruları filtrele ve sırala
    questions = Question.query.filter_by(
        class_year=class_year,
        committee=committee,
        exam_number=exam_number
    ).order_by(Question.question_number.asc()).all()
    
    return render_template('questions.html',
                         questions=questions,
                         class_year=class_year,
                         committee=committee,
                         exam_number=exam_number)

@app.route('/save_answers', methods=['POST'])
def save_answers():
    try:
        data = request.get_json()
        
        if not data or 'questions' not in data or 'answers' not in data:
            return jsonify({'error': 'Geçersiz veri formatı'}), 400
            
        questions = data['questions']
        answers = data['answers']
        class_year = data['class_year']
        committee = data['committee']
        exam_number = data['exam_number']
        
        duplicate_questions = []
        saved_count = 0
        
        # Her soru için veritabanına kayıt
        for i, question in enumerate(questions):
            # Benzer soru kontrolü
            if check_similar_questions(question['text']):
                duplicate_questions.append(i + 1)
                continue
                
            new_question = Question(
                question_text=question['text'],
                correct_answer=answers[i],
                class_year=class_year,
                committee=committee,
                exam_number=exam_number,
                question_number=question.get('question_number', i + 1)
            )
            db.session.add(new_question)
            saved_count += 1
        
        db.session.commit()

        # Cevaplar kaydedildikten sonra sıralama yap
        import question_sorter
        question_sorter.sort_questions_by_number()
        
        # Sonuç mesajını hazırla
        message = f'{saved_count} yeni soru kaydedildi.'
        if duplicate_questions:
            message += f' {len(duplicate_questions)} soru benzerlik nedeniyle atlandı (Soru numaraları: {", ".join(map(str, duplicate_questions))}).'
        
        return jsonify({
            'success': True,
            'message': message,
            'duplicate_questions': duplicate_questions
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@app.route('/quiz')
def quiz():
    # Veritabanından tüm soruları al ve kategorilere göre grupla
    questions = Question.query.with_entities(
        Question.class_year,
        Question.committee,
        Question.exam_number,
        func.count().label('count')
    ).group_by(
        Question.class_year,
        Question.committee,
        Question.exam_number
    ).all()
    
    # Soru içeren kategorileri sakla
    active_categories = {}
    for q in questions:
        if q.class_year not in active_categories:
            active_categories[q.class_year] = {}
        if q.committee not in active_categories[q.class_year]:
            active_categories[q.class_year][q.committee] = []
        active_categories[q.class_year][q.committee].append(q.exam_number)
    
    # Sınıf ve komite bilgilerini hazırla (sadece aktif olanlar)
    class_committees = {}
    for class_year, committees in active_categories.items():
        class_committees[class_year] = {
            'committees': sorted(list(committees.keys())),  # Aktif komiteler
            'exams': {committee: sorted(exams) for committee, exams in committees.items()}  # Her komite için aktif sınavlar
        }
    
    return render_template('quiz.html', class_committees=class_committees)

@app.route('/start_quiz')
def start_quiz():
    # URL parametrelerini al
    class_year = request.args.get('class_year')
    committee = request.args.get('committee')
    exam_number = request.args.get('exam_number')
    
    # Veritabanından tüm soruları çek
    questions = Question.query.filter_by(
        class_year=class_year,
        committee=committee,
        exam_number=exam_number
    ).order_by(Question.question_number.asc()).all()
    
    # Soru yoksa hata mesajı göster
    if len(questions) == 0:
        flash('Seçilen kategoride soru bulunamadı.', 'warning')
        return redirect(url_for('quiz'))
    
    return render_template('quiz_questions.html', questions=questions)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    if not query or len(query) < 3:
        flash('Lütfen en az 3 karakter içeren bir arama terimi girin.', 'warning')
        return redirect(request.referrer or url_for('index'))
    
    # Arama sorgusunu hazırla (büyük-küçük harf duyarsız)
    search_term = f"%{query}%"
    
    # Veritabanında ara
    questions = Question.query.filter(
        Question.question_text.ilike(search_term)
    ).order_by(
        Question.class_year,
        Question.committee,
        Question.exam_number,
        Question.question_number
    ).all()
    
    return render_template('search_results.html', 
                         questions=questions,
                         query=query)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=1881) 