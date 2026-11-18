import google.generativeai as genai

# API key (move this to .env later)
genai.configure(api_key="AIzaSyCXzD9Lw87LvUJ6j2e2OD4UNVvPgFQ8ehs")

try:
    # Use updated model
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content("Hello Gemini! Can you generate a short motivational quote?")
    print("✅ Gemini Response:\n", response.text)
except Exception as e:
    print("❌ Error:", e)
