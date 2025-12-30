import os
import logging
import json
import google.generativeai as genai

# Configuration
API_KEY = os.getenv("GEMINI_API_KEY")

if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash") # Using flash for speed/cost
else:
    model = None
    logging.error("GEMINI_API_KEY not found. AI features will fail.")

def generate_coaching_plan(meeting_title: str, client_name: str, client_company: str, start_time: str) -> dict:
    """
    Generates a pre-meeting coaching plan in JSON format.
    """
    if not model:
        return {}

    prompt = f"""
    You are an expert Sales Coach AI. 
    A salesperson has a new meeting upcoming.
    
    DETAILS:
    - Meeting Title: {meeting_title}
    - Client Name: {client_name}
    - Client Company: {client_company}
    - Time: {start_time}

    TASK:
    Generate a coaching plan in JSON format.
    1. 'greeting': A motivating, professional greeting.
    2. 'scenario': A 1-sentence summary of what this meeting likely involves based on the title.
    3. 'steps': 3 concise, actionable bullet points for preparation.
    4. 'recommended_reply': A short, professional acknowledgement message the salesperson can say to you (the bot).

    Schema: {{ "greeting": "...", "scenario": "...", "steps": ["...", "...", "..."], "recommended_reply": "..." }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        text = response.text.strip()
        # Clean potential markdown fences just in case
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.strip("```")
            
        return json.loads(text)
    except Exception as e:
        logging.error(f"Gemini JSON Gen Error: {e}")
        # Return fallback structure
        return {
            "greeting": "Hello!",
            "scenario": "Upcoming client meeting.",
            "steps": ["Review client history", "Check agenda", "Prepare questions"],
            "recommended_reply": "Ready to go."
        }

def generate_chat_reply(history_context: str, user_message: str) -> str:
    """
    Generates a conversational reply for roleplay or advice.
    """
    if not model:
        return "AI Service Unavailable."

    prompt = f"""
    You are a sales coach.
    Context: {history_context}
    
    The salesperson just said: "{user_message}"
    
    Provide a short, helpful coaching tip or answer. Be concise (under 50 words).
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini Chat Error: {e}")
        return "Thinking..."
