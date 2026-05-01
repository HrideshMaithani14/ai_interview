import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
api_key = os.environ.get('GEMINI_API_KEY')
print("API Key loaded:", bool(api_key))
genai.configure(api_key=api_key)

try:
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content('hello')
    print("Flash success:", response.text)
except Exception as e:
    print("Flash error:", str(e))
    
try:
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content('hello')
    print("Pro success:", response.text)
except Exception as e:
    print("Pro error:", str(e))
