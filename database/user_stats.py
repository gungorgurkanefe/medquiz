from datetime import datetime, timedelta
from .supabase import supabase

def get_user_statistics(user_id):
    """Kullanıcının istatistiklerini getir"""
    try:
        # Önce mevcut istatistikleri kontrol et
        response = supabase.table('user_statistics').select('*').eq('user_id', user_id).execute()
        
        # Eğer kayıt varsa döndür
        if response.data and len(response.data) > 0:
            return response.data[0]
            
        # Kayıt yoksa yeni oluştur
        default_stats = {
            'user_id': user_id,
            'solved_questions': 0,
            'correct_answers': 0,
            'uploaded_questions': 0,
            'study_time_minutes': 0,
            'last_activity': datetime.utcnow().isoformat()
        }
        
        try:
            insert_response = supabase.table('user_statistics').insert(default_stats).execute()
            if insert_response.data and len(insert_response.data) > 0:
                return insert_response.data[0]
        except Exception as insert_error:
            print(f"Yeni kayıt oluşturma hatası: {str(insert_error)}")
            
        return default_stats
        
    except Exception as e:
        print(f"İstatistik getirme hatası: {str(e)}")
        return {
            'solved_questions': 0,
            'correct_answers': 0,
            'uploaded_questions': 0,
            'study_time_minutes': 0,
            'last_activity': datetime.utcnow().isoformat()
        }

def update_solved_question(user_id, is_correct=False):
    """Çözülen soru istatistiğini güncelle"""
    try:
        stats = get_user_statistics(user_id)
        if not stats:
            return
            
        updates = {
            'solved_questions': int(stats.get('solved_questions', 0) or 0) + 1,
            'correct_answers': int(stats.get('correct_answers', 0) or 0) + (1 if is_correct else 0),
            'last_activity': datetime.utcnow().isoformat()
        }
        
        try:
            supabase.table('user_statistics').update(updates).eq('user_id', user_id).execute()
        except Exception as update_error:
            print(f"İstatistik güncelleme hatası: {str(update_error)}")
            
    except Exception as e:
        print(f"Soru çözme istatistiği güncelleme hatası: {str(e)}")

def update_uploaded_question(user_id):
    """Yüklenen soru istatistiğini güncelle"""
    try:
        stats = get_user_statistics(user_id)
        if not stats:
            return
            
        updates = {
            'uploaded_questions': int(stats.get('uploaded_questions', 0) or 0) + 1,
            'last_activity': datetime.utcnow().isoformat()
        }
        
        try:
            supabase.table('user_statistics').update(updates).eq('user_id', user_id).execute()
        except Exception as update_error:
            print(f"İstatistik güncelleme hatası: {str(update_error)}")
            
    except Exception as e:
        print(f"Soru yükleme istatistiği güncelleme hatası: {str(e)}")

def update_study_time(user_id, minutes):
    """Çalışma süresini güncelle"""
    try:
        stats = get_user_statistics(user_id)
        if not stats:
            return
            
        updates = {
            'study_time_minutes': int(stats.get('study_time_minutes', 0) or 0) + minutes,
            'last_activity': datetime.utcnow().isoformat()
        }
        
        try:
            supabase.table('user_statistics').update(updates).eq('user_id', user_id).execute()
        except Exception as update_error:
            print(f"İstatistik güncelleme hatası: {str(update_error)}")
            
    except Exception as e:
        print(f"Çalışma süresi güncelleme hatası: {str(e)}")

def get_last_30_days_stats(user_id):
    """Son 30 günlük istatistikleri getir"""
    try:
        stats = get_user_statistics(user_id)
        return {'solved_questions': int(stats.get('solved_questions', 0) or 0)}
    except Exception as e:
        print(f"30 günlük istatistik getirme hatası: {str(e)}")
        return {'solved_questions': 0}

def get_weekly_study_time(user_id):
    """Bu haftaki çalışma süresini getir"""
    try:
        stats = get_user_statistics(user_id)
        minutes = int(stats.get('study_time_minutes', 0) or 0)
        return round(minutes / 60, 1)  # Saate çevir
    except Exception as e:
        print(f"Haftalık çalışma süresi getirme hatası: {str(e)}")
        return 0

def calculate_success_rate(user_id):
    """Doğru cevap oranını hesapla"""
    try:
        stats = get_user_statistics(user_id)
        solved = int(stats.get('solved_questions', 0) or 0)
        correct = int(stats.get('correct_answers', 0) or 0)
        
        if solved > 0:
            rate = (correct / solved) * 100
            return round(rate, 1)
        return 0
    except Exception as e:
        print(f"Başarı oranı hesaplama hatası: {str(e)}")
        return 0 