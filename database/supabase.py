from supabase import create_client
import os
from dotenv import load_dotenv
import traceback

load_dotenv()

supabase_url = os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('NEXT_PUBLIC_SUPABASE_ANON_KEY')

supabase = create_client(supabase_url, supabase_key)

def get_user_by_email(email):
    try:
        # Doğrudan users tablosundan sorgula
        user_response = supabase.table('users').select('*').eq('email', email).execute()
        return user_response.data[0] if user_response.data else None
    except Exception as e:
        print(f"Error in get_user_by_email: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return None

def create_user(email, hashed_password, name):
    try:
        # Auth sisteminde kullanıcı oluştur (orijinal şifreyi kullan)
        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": hashed_password[:72]  # Maksimum 72 karakter
        })
        
        if auth_response.user:
            # Users tablosuna ek bilgileri kaydet
            user_data = {
                'id': auth_response.user.id,
                'email': email,
                'name': name
            }
            print(f"Attempting to create user with data: {user_data}")
            response = supabase.table('users').insert(user_data).execute()
            print(f"Supabase response: {response}")
            return response.data[0] if response.data else None
        return None
    except Exception as e:
        print(f"Error in create_user: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return None

def verify_user(email, password):
    try:
        # Auth sistemini kullanarak giriş yap
        auth_response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password[:72]  # Maksimum 72 karakter
        })
        
        if auth_response.user:
            # Kullanıcı bilgilerini users tablosundan al
            user_response = supabase.table('users').select('*').eq('email', email).execute()
            return user_response.data[0] if user_response.data else None
        return None
    except Exception as e:
        print(f"Error in verify_user: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return None 