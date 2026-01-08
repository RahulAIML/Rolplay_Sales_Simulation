# Outlook -> Gemini -> WhatsApp Automation

A Proof-of-Concept to process Outlook meetings with Google Gemini and notify via Twilio WhatsApp.

## Setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your keys (Gemini, Twilio).
3. Run `python app.py`.
4. Start ngrok: `ngrok http 5000`.

## Configuration
- **Make.com**: Create a scenario "Watch Events (Outlook)" -> "HTTP Request" (POST to `[ngrok-url]/outlook-webhook` with JSON body).
- **Twilio**: Set Sandbox Webhook to `[ngrok-url]/whatsapp-reply`.
