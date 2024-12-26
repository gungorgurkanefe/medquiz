import sqlite3
from difflib import SequenceMatcher
import re

class QuestionValidator:
    def __init__(self, db_path):
        self.db_path = db_path
        self.similarity_threshold = 0.85  # %85 benzerlik eşiği
    
    def get_db_connection(self):
        return sqlite3.connect(self.db_path)
    
    def clean_text(self, text):
        """Metni karşılaştırma için temizler ve normalleştirir."""
        # Tüm metni küçük harfe çevir
        text = text.lower()
        # Gereksiz boşlukları temizle
        text = re.sub(r'\s+', ' ', text)
        # Noktalama işaretlerini kaldır
        text = re.sub(r'[^\w\s]', '', text)
        return text.strip()
    
    def calculate_similarity(self, text1, text2):
        """İki metin arasındaki benzerlik oranını hesaplar"""
        # Metinleri küçük harfe çevir ve gereksiz boşlukları temizle
        text1 = ' '.join(text1.lower().split())
        text2 = ' '.join(text2.lower().split())
        
        # SequenceMatcher kullanarak benzerlik oranını hesapla
        return SequenceMatcher(None, text1, text2).ratio()
    
    def is_duplicate_question(self, question_text, class_year, committee):
        """Veritabanında benzer soru olup olmadığını kontrol eder"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Aynı sınıf ve komitedeki soruları al
            c.execute('''SELECT id, question_text FROM questions 
                        WHERE class_year = ? AND committee = ?''',
                     (class_year, committee))
            
            existing_questions = c.fetchall()
            max_similarity = 0
            similar_id = None
            
            # Her mevcut soru için benzerlik kontrolü yap
            for q_id, q_text in existing_questions:
                similarity = self.calculate_similarity(question_text, q_text)
                if similarity > max_similarity:
                    max_similarity = similarity
                    similar_id = q_id
            
            # Benzerlik eşiği (0.8 = %80 benzerlik)
            is_duplicate = max_similarity >= 0.8
            
            conn.close()
            return is_duplicate, similar_id, max_similarity
            
        except Exception as e:
            print(f"Benzerlik kontrolünde hata: {str(e)}")
            return False, None, 0
    
    def check_questions_batch(self, questions, class_year=None, committee=None):
        """
        Birden fazla soruyu toplu olarak kontrol eder.
        
        Args:
            questions (list): Kontrol edilecek soru metinleri listesi
            class_year (int, optional): Sınıf yılı
            committee (int, optional): Komite numarası
            
        Returns:
            list: Her soru için (soru_metni, is_duplicate, similar_question_id, similarity_ratio) tuple'larından oluşan liste
        """
        results = []
        for question in questions:
            is_duplicate, similar_id, similarity = self.is_duplicate_question(
                question, class_year, committee
            )
            results.append((question, is_duplicate, similar_id, similarity))
        return results
    
    def get_similar_questions(self, question_text, class_year=None, committee=None, limit=5):
        """
        Verilen soruya benzer soruları bulur.
        
        Args:
            question_text (str): Aranan soru metni
            class_year (int, optional): Sınıf yılı
            committee (int, optional): Komite numarası
            limit (int): Maksimum dönülecek benzer soru sayısı
            
        Returns:
            list: (soru_id, soru_metni, benzerlik_oranı) tuple'larından oluşan liste
        """
        conn = self.get_db_connection()
        c = conn.cursor()
        
        try:
            query = "SELECT id, question_text FROM questions"
            params = []
            conditions = []
            
            if class_year is not None:
                conditions.append("class_year = ?")
                params.append(class_year)
            
            if committee is not None:
                conditions.append("committee = ?")
                params.append(committee)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            c.execute(query, params)
            existing_questions = c.fetchall()
            
            # Benzerlik oranlarını hesapla ve sırala
            similar_questions = []
            for q_id, q_text in existing_questions:
                similarity = self.calculate_similarity(question_text, q_text)
                similar_questions.append((q_id, q_text, similarity))
            
            # Benzerlik oranına göre sırala ve limit kadar döndür
            similar_questions.sort(key=lambda x: x[2], reverse=True)
            return similar_questions[:limit]
            
        finally:
            conn.close() 