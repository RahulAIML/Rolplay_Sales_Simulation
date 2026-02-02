# Bot Account Setup Guide (Admin)

This document provides comprehensive instructions for setting up and managing the two bot accounts used by the Rolplay Sales Automation system.

## Bot Account Information

The system uses **two bot email accounts** to monitor calendar invitations and trigger coaching workflows:

1. **Primary Gmail Bot**: `bhattacharyabuddhadeb147@gmail.com`
2. **Secondary Outlook Bot**: `bhattacharyabuddhadeb@outlook.com`

> **Important**: Users must invite **BOTH** accounts to their meetings for the system to function properly.

---

## Initial Setup

### 1. Gmail Bot Account Setup

**Account**: `bhattacharyabuddhadeb147@gmail.com`

#### Steps:
1. **Access the Account**: Log into the Gmail account using the credentials.
2. **Enable Calendar**: Ensure Google Calendar is enabled for this account.
3. **Calendar Permissions**: Set the calendar to accept meeting invitations automatically (Settings → Event Settings → "Automatically add invitations").
4. **API Access**: If using Google Calendar API for integration:
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create/select a project
   - Enable Google Calendar API
   - Create service account credentials
   - Grant calendar access to the service account

### 2. Outlook Bot Account Setup

**Account**: `bhattacharyabuddhadeb@outlook.com`

#### Steps:
1. **Access the Account**: Log into the Outlook account.
2. **Calendar Settings**: 
   - Navigate to Outlook Calendar settings
   - Enable automatic acceptance of meeting invitations if available
3. **Azure Integration** (if using Microsoft Graph API):
   - Register the app in [Azure Portal](https://portal.azure.com)
   - Configure API permissions: `Calendars.Read`, `Calendars.ReadWrite`
   - Note the Client ID, Client Secret, and Tenant ID

---

## Integration with Make.com

The bot accounts are monitored by **Make.com scenarios** that watch for new calendar events and trigger webhooks to the backend.

### Scenario Configuration

1. **Create a Make.com Scenario**:
   - Trigger: **Watch Calendar Events** (Google Calendar or Microsoft Outlook module)
   - Connect each bot account to its respective module

2. **Configure Webhook**:
   - Action: **HTTP Request**
   - URL: `https://your-app.onrender.com/outlook-webhook`
   - Method: `POST`
   - Body (JSON):
     ```json
     {
       "meeting": {
         "title": "{{event.Subject}}",
         "start_time": "{{event.start}}",
         "end_time": "{{event.end}}",
         "meeting_id": "{{event.id}}",
         "subject": "{{event.Subject}}",
         "body": "{{event.Body.Content}}",
         "body_type": "{{event.Body.ContentType}}",
         "location": {
           "display_name": "{{event.Location.DisplayName}}",
           "address": "{{event.Location.Address}}",
           "coordinates": "{{event.Location.Coordinates}}"
         },
         "is_online_meeting": "{{event.IsOnlineMeeting}}",
         "online_meeting_url": "{{event.OnlineMeeting.JoinUrl}}",
         "online_meeting_provider": "{{event.OnlineMeetingProvider}}",
         "organizer": {
           "name": "{{event.Organizer.EmailAddress.Name}}",
           "address": "{{event.Organizer.EmailAddress.Address}}"
         },
         "attendees": {{event.Attendees}},
         "is_all_day": "{{event.IsAllDay}}",
         "is_cancelled": "{{event.IsCancelled}}",
         "sensitivity": "{{event.Sensitivity}}",
         "show_as": "{{event.ShowAs}}",
         "importance": "{{event.Importance}}",
         "response_status": "{{event.ResponseStatus}}",
         "created_datetime": "{{event.CreatedDateTime}}",
         "last_modified_datetime": "{{event.LastModifiedDateTime}}"
       },
       "client": {
         "first_name": "{{attendee.firstName}}",
         "last_name": "{{attendee.lastName}}",
         "name": "{{attendee.name}}",
         "email": "{{attendee.email}}",
         "company": "{{company}}",
         "phone": "{{attendee.phone}}",
         "hubspot_contact_id": "{{hubspot_contact_id}}"
       }
     }
     ```
     
     **Enhanced Fields Included**:
     - **Meeting Metadata**: ID, body/agenda, creation/modification timestamps
     - **Location Details**: Physical location or online meeting URL
     - **Online Meeting Support**: Teams/Zoom links, provider information
     - **Attendee List**: Full list of all meeting participants
     - **Meeting Status**: All-day flag, cancellation status, importance level
     - **Client Details**: Separated first/last name, phone number
     
     > **Note**: All fields are optional. The backend gracefully handles missing data with its key normalization logic.

3. **Schedule**: Set the scenario to run every 15 minutes or use real-time webhooks if available.

---

## Environment Configuration

Update your `.env` file (both locally and on Render) with the bot email addresses:

```bash
# Bot Email Accounts (users must invite both)
BOT_EMAIL_PRIMARY=bhattacharyabuddhadeb147@gmail.com
BOT_EMAIL_SECONDARY=bhattacharyabuddhadeb@outlook.com
```

### Render Deployment

1. Go to your Render dashboard
2. Navigate to your web service
3. Click **Environment** → **Add Environment Variable**
4. Add both `BOT_EMAIL_PRIMARY` and `BOT_EMAIL_SECONDARY`
5. Save and redeploy

---

## Security Best Practices

### Account Security
- ✅ Enable **2-Factor Authentication** on both bot accounts
- ✅ Use **strong, unique passwords**
- ✅ Store credentials securely (password manager)
- ✅ Limit access to bot account credentials to essential personnel only

### API Security
- ✅ Use **service accounts** instead of personal accounts where possible
- ✅ Apply **principle of least privilege** (minimal required permissions)
- ✅ Rotate API keys/secrets periodically
- ✅ Monitor API usage for anomalies

### Privacy
- ⚠️ Bot accounts can view meeting details of all invited meetings
- ⚠️ Ensure compliance with data privacy regulations (GDPR, etc.)
- ⚠️ Document what data is collected and how it's used

---

## Monitoring & Maintenance

### Regular Checks
- **Weekly**: Verify bot accounts are still receiving invitations
- **Monthly**: Review Make.com scenario execution logs
- **Quarterly**: Audit user registrations and meeting activity

### Troubleshooting

#### Bot not receiving coaching
**Possible causes:**
- User forgot to invite one or both bot accounts
- Make.com scenario is paused or failing
- API credentials expired
- Backend webhook endpoint is down

**Resolution:**
1. Check Make.com scenario status
2. Verify webhook endpoint is reachable (`/health` endpoint)
3. Check backend logs for errors
4. Confirm bot accounts are actually invited to the meeting

#### Duplicate notifications
**Possible causes:**
- Both bot accounts triggering separate webhooks
- Make.com scenario running multiple times

**Resolution:**
- Add deduplication logic in backend (check if meeting already processed)
- Use a unique `outlook_event_id` to track meetings

---

## User Communication

When onboarding new users:

1. **Emphasize BOTH**: Make it crystal clear that users must invite both email addresses
2. **Provide Examples**: Show screenshots of how to add both attendees in Outlook/Gmail
3. **Troubleshooting**: If a user reports not receiving coaching, first check if they invited both accounts

---

## Migration Notes

### Previous Bot Email
The system previously used `coachlink360@outlook.com`. If you have existing users:

1. **Communication**: Notify all registered users of the new bot emails
2. **Transition Period**: Consider monitoring the old bot email during transition
3. **Update Documentation**: Ensure all user-facing docs reflect the new accounts

---

## Contact & Support

For issues with bot account access or integration:
- **System Admin**: [Your contact information]
- **Make.com Support**: https://www.make.com/en/help
- **Backend Logs**: Check Render dashboard for application logs
