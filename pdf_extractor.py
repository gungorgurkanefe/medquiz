import sys
import os
import time
import sqlite3
import google.generativeai as genai
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QComboBox, QPushButton, 
                            QFileDialog, QProgressBar, QMessageBox, QTextEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from pdf2image import convert_from_path
from PIL import Image
import re
from pathlib import Path

class QuestionExtractorThread(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, pdf_path, class_year, committee, exam_number):
        super().__init__()
        self.pdf_path = pdf_path
        self.class_year = class_year
        self.committee = committee
        self.exam_number = exam_number
        self.last_request_time = 0
        self.requests_this_minute = 0

        # Gemini API yapılandırması
        GEMINI_API_KEY = "AIzaSyDqbTC7P8NDuH9bkJZ2xtb6nodcE6UsEiE"
        genai.configure(api_key=GEMINI_API_KEY)

        # Model yapılandırması
        generation_config = genai.types.GenerationConfig(
            temperature=1.0,
            max_output_tokens=8192,
            top_p=1.0,
            top_k=40
        )
        self.model = genai.GenerativeModel('gemini-1.5-flash-002', generation_config=generation_config)

    def can_make_request(self):
        current_time = time.time()
        
        if current_time - self.last_request_time >= 60:
            self.requests_this_minute = 0
            self.last_request_time = current_time
        
        if self.requests_this_minute < 15:
            self.requests_this_minute += 1
            return True
        return False

    def extract_questions(self, text):
        questions = []
        current_question = None
        current_options = []
        question_text_buffer = []
        current_question_number = None
        processed_numbers = set()  # İşlenen soru numaralarını takip etmek için
        
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
                    if len(current_options) == 5 and current_question_number not in processed_numbers:
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
                            if len(content) < 2:
                                print(f"Şık içeriği çok kısa: {opt}")
                                valid_options = False
                                break
                                
                            # Şıkkın tam olduğunu kontrol et
                            if content.endswith('...') or content.endswith('…'):
                                print(f"Yarım kalmış şık: {opt}")
                                valid_options = False
                                break
                                
                            # "not visible" veya "undefined" gibi API hata mesajlarını kontrol et
                            if any(x in content.lower() for x in ['undefined', 'not visible', 'not fully visible', 'option e is not']):
                                print(f"Geçersiz şık içeriği: {opt}")
                                valid_options = False
                                break
                        
                        if valid_options:
                            full_question = {
                                'text': current_question + '\n\n' + '\n'.join(current_options),
                                'number': current_question_number
                            }
                            questions.append(full_question)
                            processed_numbers.add(current_question_number)
                            print(f"Soru eklendi: {current_question[:100]}...")
                        else:
                            print(f"Soru atlandı (geçersiz şık formatı): {current_question[:100]}...")
                    else:
                        if current_question_number in processed_numbers:
                            print(f"Soru zaten işlenmiş: {current_question[:100]}...")
                        else:
                            print(f"Soru atlandı (şık sayısı {len(current_options)}): {current_question[:100]}...")
                
                # Soru numarasını al
                match = re.match(r'^(\d+)\.', line)
                current_question_number = int(match.group(1))
                
                # Eğer soru zaten işlenmişse atla
                if current_question_number in processed_numbers:
                    current_question = None
                    current_options = []
                    in_question = False
                    in_options = False
                    continue
                    
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
        if current_question and current_options and current_question_number not in processed_numbers:
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
                        
                    if any(x in content.lower() for x in ['undefined', 'not visible', 'not fully visible', 'option e is not']):
                        print(f"Geçersiz şık içeriği: {opt}")
                        valid_options = False
                        break
                
                if valid_options:
                    full_question = {
                        'text': current_question + '\n\n' + '\n'.join(current_options),
                        'number': current_question_number
                    }
                    questions.append(full_question)
                    processed_numbers.add(current_question_number)
                    print(f"Son soru eklendi: {current_question[:100]}...")
                else:
                    print(f"Son soru atlandı (geçersiz şık formatı): {current_question[:100]}...")
            else:
                print(f"Son soru atlandı (şık sayısı {len(current_options)}): {current_question[:100]}...")
        
        print(f"\nToplam {len(questions)} soru işlendi")
        return questions

    def run(self):
        try:
            # PDF'yi görüntülere dönüştür
            images = convert_from_path(self.pdf_path)
            total_pages = len(images)
            extracted_questions = []
            
            for i, image in enumerate(images):
                self.progress.emit(int((i / total_pages) * 100))
                self.status.emit(f"Sayfa {i+1}/{total_pages} işleniyor...")
                
                # Rate limit kontrolü
                while not self.can_make_request():
                    self.status.emit("Rate limit aşıldı. Bekleniyor...")
                    time.sleep(1)
                
                try:
                    # Gemini API'ye gönder
                    response = self.model.generate_content([
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
                        image
                    ])
                    
                    # Soruları çıkar
                    questions = self.extract_questions(response.text)
                    if questions:
                        extracted_questions.extend(questions)
                    
                except Exception as e:
                    self.error.emit(f"Sayfa {i+1} işlenirken hata: {str(e)}")
                    continue
            
            self.progress.emit(100)
            self.status.emit("İşlem tamamlandı!")
            self.finished.emit(extracted_questions)
            
        except Exception as e:
            self.error.emit(f"PDF işlenirken hata: {str(e)}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Soru Çıkarıcı")
        self.setMinimumSize(800, 600)
        
        # Ana widget ve layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Dosya seçimi
        file_layout = QHBoxLayout()
        self.file_label = QLabel("PDF Seçilmedi")
        file_button = QPushButton("PDF Seç")
        file_button.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(file_button)
        layout.addLayout(file_layout)
        
        # Sınıf seçimi
        class_layout = QHBoxLayout()
        class_layout.addWidget(QLabel("Sınıf:"))
        self.class_combo = QComboBox()
        self.class_combo.addItems(["1", "2", "3"])
        self.class_combo.currentTextChanged.connect(self.update_committees)
        class_layout.addWidget(self.class_combo)
        layout.addLayout(class_layout)
        
        # Komite seçimi
        committee_layout = QHBoxLayout()
        committee_layout.addWidget(QLabel("Komite:"))
        self.committee_combo = QComboBox()
        committee_layout.addWidget(self.committee_combo)
        layout.addLayout(committee_layout)
        
        # Sınav seçimi
        exam_layout = QHBoxLayout()
        exam_layout.addWidget(QLabel("Sınav:"))
        self.exam_combo = QComboBox()
        self.exam_combo.addItems([
            "2024/2025",
            "2023/2024",
            "2022/2023",
            "2021/2022",
            "2020/2021",
            "2019/2020",
            "2018/2019",
            "2017/2018",
            "2016/2017",
            "2015/2016",
            "Bilinmeyen Yıl"
        ])
        exam_layout.addWidget(self.exam_combo)
        layout.addLayout(exam_layout)
        
        # İşlem butonu
        self.process_button = QPushButton("İşlemi Başlat")
        self.process_button.clicked.connect(self.start_processing)
        self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)
        
        # İlerleme çubuğu
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        # Durum mesajı
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        
        # Log alanı
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        
        # Veritabanı bağlantısını başlat
        self.init_db()
        
        # İlk komite listesini yükle
        self.update_committees()
        
        self.pdf_path = None
        self.extractor_thread = None

    def init_db(self):
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
        self.db_path = db_path

    def update_committees(self):
        self.committee_combo.clear()
        class_year = int(self.class_combo.currentText())
        
        if class_year in [1, 2]:
            self.committee_combo.addItems([str(i) for i in range(1, 6)])  # 1-5 arası komite
        else:
            self.committee_combo.addItems([str(i) for i in range(1, 7)])  # 1-6 arası komite

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "PDF Seç", "", "PDF Dosyaları (*.pdf)")
        if file_path:
            self.pdf_path = file_path
            self.file_label.setText(os.path.basename(file_path))
            self.process_button.setEnabled(True)

    def log_message(self, message):
        self.log_text.append(message)

    def save_questions(self, questions):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        saved_count = 0
        duplicate_count = 0
        
        for question in questions:
            # Soru metnini ve şıkları ayır
            parts = question['text'].split('\n\n')
            if len(parts) >= 2:
                question_text = parts[0].strip()
                options_text = parts[1]
                
                # Şıkları parse et
                options = {}
                for line in options_text.split('\n'):
                    if line.strip():
                        option_match = re.match(r'^([A-E])\)(.*?)$', line.strip())
                        if option_match:
                            options[option_match.group(1)] = option_match.group(2).strip()
                
                if len(options) == 5:  # Sadece 5 şıkkı olan soruları kaydet
                    try:
                        # Soru metninin benzerliğini kontrol et
                        c.execute('''SELECT id, question_text, option_a, option_b, option_c, option_d, option_e 
                                   FROM questions''')
                        existing_questions = c.fetchall()
                        
                        is_duplicate = False
                        for existing in existing_questions:
                            # Soru metni benzerliğini kontrol et
                            similarity_ratio = self.calculate_similarity(question_text, existing[1])
                            
                            # Şıkların benzerliğini kontrol et
                            options_similarity = all(
                                self.calculate_similarity(options[opt], existing[i+2]) > 0.8
                                for i, opt in enumerate(['A', 'B', 'C', 'D', 'E'])
                            )
                            
                            # Eğer hem soru metni hem de şıklar benzer ise
                            if similarity_ratio > 0.8 and options_similarity:
                                print(f"Benzer soru bulundu (Soru #{question['number']})")
                                duplicate_count += 1
                                is_duplicate = True
                                break
                        
                        if is_duplicate:
                            continue
                        
                        # Soru veritabanında yoksa ekle
                        c.execute('''INSERT INTO questions 
                                    (question_text, option_a, option_b, option_c, option_d, option_e, 
                                     correct_answer, class_year, committee, exam_number, question_number)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (question_text, options['A'], options['B'], options['C'], 
                                 options['D'], options['E'], 'A', int(self.class_combo.currentText()),
                                 int(self.committee_combo.currentText()),
                                 self.exam_combo.currentIndex() + 1, question['number']))
                        saved_count += 1
                        print(f"Soru #{question['number']} veritabanına eklendi")
                    except sqlite3.Error as e:
                        self.log_message(f"Veritabanı hatası: {str(e)}")
        
        conn.commit()
        conn.close()
        
        if duplicate_count > 0:
            self.log_message(f"\n{duplicate_count} benzer soru bulunduğu için atlandı.")
        
        return saved_count

    def calculate_similarity(self, text1, text2):
        """İki metin arasındaki benzerlik oranını hesaplar"""
        # Metinleri küçük harfe çevir ve gereksiz boşlukları temizle
        text1 = ' '.join(text1.lower().split())
        text2 = ' '.join(text2.lower().split())
        
        # Levenshtein mesafesini hesapla
        distance = self.levenshtein_distance(text1, text2)
        max_length = max(len(text1), len(text2))
        
        # Benzerlik oranını hesapla (0-1 arası)
        if max_length == 0:
            return 0
        return 1 - (distance / max_length)

    def levenshtein_distance(self, s1, s2):
        """İki metin arasındaki Levenshtein mesafesini hesaplar"""
        if len(s1) < len(s2):
            return self.levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]

    def start_processing(self):
        if not self.pdf_path:
            QMessageBox.warning(self, "Hata", "Lütfen bir PDF dosyası seçin.")
            return
        
        self.process_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        
        # İşlem thread'ini başlat
        self.extractor_thread = QuestionExtractorThread(
            self.pdf_path,
            int(self.class_combo.currentText()),
            int(self.committee_combo.currentText()),
            self.exam_combo.currentIndex() + 1
        )
        
        self.extractor_thread.progress.connect(self.progress_bar.setValue)
        self.extractor_thread.status.connect(self.status_label.setText)
        self.extractor_thread.status.connect(self.log_message)
        self.extractor_thread.error.connect(self.log_message)
        self.extractor_thread.finished.connect(self.process_finished)
        
        self.extractor_thread.start()

    def process_finished(self, questions):
        saved_count = self.save_questions(questions)
        self.log_message(f"\nToplam {saved_count} soru veritabanına kaydedildi.")
        self.process_button.setEnabled(True)
        QMessageBox.information(self, "Başarılı", f"İşlem tamamlandı! {saved_count} soru kaydedildi.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_()) 