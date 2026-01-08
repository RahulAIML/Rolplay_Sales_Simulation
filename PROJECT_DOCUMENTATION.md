# ROLPLAY Sales Automation - Project Documentation

## 1. Executive Summary
**ROLPLAY Sales Automation** (also known as Sales Coach AI) is an intelligent system designed to assist salespeople by providing real-time, AI-driven coaching before and after client meetings. It integrates seamlessly with **Outlook Calendar**, **WhatsApp**, **HubSpot CRM**, and **Google Gemini AI** to deliver personalized coaching plans, automated reminders, and effortless data entry.

The system is designed to be "invisible" to the end-user setup, allowing managers to onboard simply by registering their details, after which the system works automatically by being invited to calendar events.

---

## 2. System Architecture

## 2. System Architecture

### High-Level Flow (Bot-as-Attendee Model)
1.  **Meeting Scheduled**: A Registered User creates a meeting in their Outlook and invites the **Bot Email** (e.g., `coach-bot@rolplay.ai`) as an attendee.
2.  **Ingestion**: A **Central Make.com Scenario** (Admin managed) monitors the Bot's calendar for new invitations.
3.  **Webhook**: The scenario extracts meeting details and sends a payload to the backend.
4.  **Salesperson Identification**: The system matches the meeting **Organizer's Email** to a registered user in the database.
5.  **AI Analysis**: Google Gemini generates a coaching plan.
6.  **Delivery**: The plan is sent to the *Salesperson's* WhatsApp number.
6.  **Interaction**: The salesperson interacts with the bot on WhatsApp for roleplay/advice.
7.  **Completion & Sync**: After the meeting, the system sends a reminder. When the salesperson replies with feedback (e.g., "Done"), the system logs the outcome to HubSpot and marks the meeting as complete.

### Tech Stack
*   **Language**: Python 3.10+
*   **Framework**: Flask
*   **AI Engine**: Google Gemini (via `google-generativeai`)
*   **Database**: 
    *   **Local**: SQLite (`coachlink.db`)
    *   **Production**: PostgreSQL (via `psycopg2`)
*   **Communication**: Twilio API (WhatsApp)
*   **CRM**: HubSpot API
*   **Task Scheduling**: APScheduler (Background Scheduler)
*   **Deployment**: Render (Gunicorn)

---

## 3. Key Features

### 🚀 Smart Onboarding
*   **Web Form**: Simple `/register` endpoint allowing users to sign up with Name, Email, and WhatsApp number.
*   **Phone Normalization**: Automatically formats phone numbers for WhatsApp compatibility.
*   **Immediate Confirmation**: Sends a "Welcome" WhatsApp message immediately upon registration to verify the phone number.

### 🤖 AI Coaching
*   **Pre-Meeting Prep**: Delivers a structured JSON-based plan including a scenario summary and 3 actionable steps.
*   **Dynamic Chat**: Users can reply to the bot to ask for advice or roleplay specific objections. The bot maintains context of the current meeting.

### 📅 Automated Workflow
*   **Outlook Integration**: "Invite" the central bot email to any meeting to trigger the workflow.
*   **Reminders**: Automatically checks for finished meetings every 60 seconds and sends a reminder 1 minute after the scheduled end time.

### 🔄 CRM Sync
*   **HubSpot Logging**: Automatically logs a meeting note to the contact in HubSpot when the user reports "Done".
*   **Contact Discovery**: Attempts to find existing HubSpot contacts by email if a direct ID is not provided.

---

## 4. Setup & Installation

### Prerequisites
*   Python 3.10 or higher
*   Twilio Account (SID, Auth Token, WhatsApp Sender)
*   Google Gemini API Key
*   HubSpot Access Token (Optional, for CRM sync)

### Local Development
1.  **Clone the Repository**:
    ```bash
    git clone <repo_url>
    cd ROLPLAY_Sales_Automation
    ```

2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Environment Configuration**:
    Create a `.env` file in the root directory:
    ```ini
    GEMINI_API_KEY=your_gemini_key
    TWILIO_ACCOUNT_SID=your_sid
    TWILIO_AUTH_TOKEN=your_token
    TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
    ADMIN_WHATSAPP_TO=whatsapp:+1234567890
    HUBSPOT_ACCESS_TOKEN=your_hubspot_token
    # DATABASE_URL=postgresql://... (Leave empty for local SQLite)
    ```

4.  **Run Application**:
    ```bash
    python app.py
    ```
    The server will start on `http://0.0.0.0:5000`.

### Database Management
The system uses a custom `DBHandler` in `database.py` that automatically switches between SQLite and PostgreSQL based on the `DATABASE_URL` environment variable.
*   **Migration**: The `init_db()` method attempts to create tables and add missing columns on startup.

---

## 5. API Reference

### `POST /register`
Registers a new salesperson.
*   **Payload (Form Data)**:
    *   `name`: Full Name
    *   `email`: Outlook Email Address
    *   `phone`: WhatsApp Number (with country code)

### `POST /outlook-webhook`
Receives meeting data from the external source.
*   **Payload (JSON)**:
    ```json
    {
      "meeting": {
        "title": "Sales Call",
        "start_time": "2023-10-27T10:00:00Z",
        "end_time": "2023-10-27T10:30:00Z",
        "organizer": {"address": "sara@company.com"}
      },
      "client": {
        "name": "John Client",
        "email": "john@client.com",
        "company": "Client Co",
        "hubspot_contact_id": "123"
      }
    }
    ```

### `POST /whatsapp-webhook`
Twilio webhook for incoming WhatsApp messages.
*   **Payload**: Standard Twilio Form Data (`Body`, `From`).

---

## 6. Deployment (Render)

The project includes a `render.yaml` Blueprint for Infrastructure-as-Code deployment.

1.  **Connect to Render**: Link your GitHub repository to Render.
2.  **Create Blueprint**: Select "New Blueprint Instance" and choose this repo.
3.  **Services Created**:
    *   **Web Service**: Python app running Gunicorn.
    *   **Database**: PostgreSQL instance.
4.  **Environment Variables**: ensuring all secrets (`GEMINI_API_KEY`, `TWILIO_*`, etc.) are populated in the Render dashboard.

---

## 7. Database Schema

### `users`
Stores registered salespeople.
*   `email` (PK): Outlook email.
*   `name`: User's name.
*   `phone`: WhatsApp number.

### `clients`
Stores client info extracted from meetings.
*   `id` (PK): Auto-incrementing ID.
*   `email`: Client email.
*   `name`, `company`, `phone`.
*   `hubspot_contact_id`: ID links to HubSpot CRM.

### `meetings`
Tracks scheduled and completed meetings.
*   `id` (PK)
*   `outlook_event_id`: Unique ID from Outlook.
*   `start_time`, `end_time`: ISO timestamps.
*   `client_id`: FK to `clients`.
*   `salesperson_phone`: Phone number of the salesperson assigned.
*   `status`: `scheduled` -> `reminder_sent` -> `completed`.
*   `last_client_reply`: Last message content.

### `messages`
Logs chat history for analysis.
*   `id` (PK)
*   `client_id`: Context of the conversation.
*   `direction`: `incoming` or `outgoing`.
*   `message`: Content.
*   `timestamp`: API timestamp.
