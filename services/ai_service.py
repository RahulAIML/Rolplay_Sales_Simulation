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

def generate_coaching_plan(meeting_title: str, client_name: str, client_company: str, start_time: str, meeting_body: str = "", location: str = "") -> dict:
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
    - Agenda/Body: {meeting_body}
    - Location: {location}

    TASK:
    Generate a coaching plan in JSON format.
    1. 'greeting': A motivating, professional greeting.
    2. 'scenario': A 1-sentence summary of what this meeting likely involves based on the title and agenda.
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
    You are a helpful Sales Coach Assistant.
    
    CONTEXT:
    {history_context}
    
    USER MESSAGE: "{user_message}"
    
    INSTRUCTIONS:
    1. If the CONTEXT contains "[FULL TRANSCRIPT AVAILABLE]", prioritize this verbatim text over any summary. Use it to answer specific questions like "Who said X?" or "What was the objection?".
    2. If the user asks a question about the meeting content, ANSWER IT based on the Context provided. Do not suggest they look elsewhere.
    3. If the user asks for advice or roleplays, provide a short, helpful coaching tip (under 50 words).
    
    Response:
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini Chat Error: {e}")
        return "Thinking..."

def generate_post_meeting_analysis(transcript_text: str) -> dict:
    """
    Analyzes the full meeting transcript to generate coaching insights.
    """
    if not model:
        # Fallback for testing/no-key scenarios
        return {
            "objections": [],
            "buying_signals": ["Mock Signal"],
            "risks": [],
            "follow_up_actions": ["Check transcript"]
        }
        
    prompt = f"""
    You are an expert Sales Coach. Analyze the following meeting transcript.
    
    TRANSCRIPT:
    {transcript_text[:100000]}  # Truncate to safety limit
    
    TASK:
    Generate a post-meeting coaching report in JSON format.
    1. 'objections': List specific client objections, quoting the exact transcript line and timestamp if available.
    2. 'buying_signals': List positive signals or interest shown by the client.
    3. 'risks': Potential risks to the deal (competitors, budget, timeline, etc.).
    4. 'follow_up_actions': Concrete next steps for the salesperson.
    
    Schema: {{ 
        "objections": [{{ "quote": "...", "context": "..." }}], 
        "buying_signals": ["...", "..."], 
        "risks": ["...", "..."], 
        "follow_up_actions": ["...", "..."] 
    }}
    """
    
    try:
        response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        text = response.text.strip()
        # Clean potential markdown
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.strip("```")
            
        return json.loads(text)
    except Exception as e:
        logging.error(f"Gemini Transcript Analysis Error: {e}")
        return {
            "objections": [],
            "buying_signals": [],
            "risks": [],
            "follow_up_actions": []
        }


def generate_sales_coaching(transcript_text: str) -> dict:
    """
    Generates structured sales coaching feedback from a full meeting transcript.
    """
    if not model:
        # Fallback for testing/no-key
        return {
            "strengths": ["Good energy"], 
            "weaknesses": ["Missed closing"], 
            "missed_opportunities": ["Did not upsell"],
            "objection_handling_score": 3,
            "communication_clarity_score": 3,
            "confidence_score": 3,
            "recommended_actions": ["Practice closing"],
            "next_meeting_tips": ["Prepare pricing"]
        }

    prompt = f"""
    You are a senior sales coach AI.

    You are given a full verbatim meeting transcript.
    Analyze the conversation and provide coaching feedback.

    TRANSCRIPT:
    {transcript_text[:150000]} # Truncate for safety

    Return JSON only with this structure:

    {{
      "strengths": [string],
      "weaknesses": [string],
      "missed_opportunities": [string],
      "objection_handling_score": 1-5,
      "communication_clarity_score": 1-5,
      "confidence_score": 1-5,
      "recommended_actions": [string],
      "next_meeting_tips": [string]
    }}

    Be honest, specific, and actionable.
    """

    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        text = response.text.strip()
        
        # Clean markdown
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.strip("```")
            
        return json.loads(text)
    except Exception as e:
        logging.error(f"Gemini Coaching Error: {e}")
        return {
            "error": "Failed to generate coaching",
            "details": str(e)
        }
