import os
from langchain.chat_models import ChatOpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def process_message_with_gpt(message: str, chat_id: str, phone: str) -> str:
    chat = ChatOpenAI(openai_api_key=OPENAI_API_KEY, model_name="gpt-4", temperature=0.7)
    # Crie um prompt básico (este pode ser refinado posteriormente)
    prompt = f"O usuário (ID: {chat_id}, Telefone: {phone}) disse: '{message}'. Responda de forma amigável e concisa."

    # Método simplificado: call_as_llm no langchain_community já não é mais padrão, agora usamos:
    response = chat.predict(prompt)
    return response
