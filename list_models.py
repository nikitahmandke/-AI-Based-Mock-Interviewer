import google.generativeai as genai

# configure with your API key
genai.configure(api_key="AIzaSyCXzD9Lw87LvUJ6j2e2OD4UNVvPgFQ8ehs")

# list all available models and their supported methods
for m in genai.list_models():
    print(m.name, "->", m.supported_generation_methods)
