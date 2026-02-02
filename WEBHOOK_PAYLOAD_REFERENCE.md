# Make.com Webhook - Enhanced JSON Payload Reference

This document provides the complete, production-ready JSON payload for the Make.com Microsoft 365 Calendar webhook.

## Full Payload Structure

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

---

## Field Descriptions

### Meeting Core Fields

| Field | Description | Example |
|-------|-------------|---------|
| `title` | Meeting title/subject | "Sales Demo with Acme Corp" |
| `start_time` | ISO 8601 start datetime | "2026-02-03T10:00:00Z" |
| `end_time` | ISO 8601 end datetime | "2026-02-03T11:00:00Z" |
| `meeting_id` | Unique Microsoft event ID | "AAMkAGI1..." |
| `subject` | Meeting subject (duplicate of title) | "Sales Demo with Acme Corp" |
| `body` | Meeting description/agenda | "Demo our new features..." |
| `body_type` | Body content format | "HTML" or "Text" |

### Location Information

| Field | Description | Example |
|-------|-------------|---------|
| `location.display_name` | Location name | "Conference Room A" |
| `location.address` | Full address (if physical) | "123 Main St, Boston MA" |
| `location.coordinates` | GPS coordinates | "42.3601,-71.0589" |
| `is_online_meeting` | Online meeting flag | true/false |
| `online_meeting_url` | Join URL for virtual meeting | "https://teams.microsoft.com/..." |
| `online_meeting_provider` | Platform used | "teamsForBusiness", "zoom" |

### Organizer & Attendees

| Field | Description | Example |
|-------|-------------|---------|
| `organizer.name` | Organizer's full name | "Sarah Manager" |
| `organizer.address` | Organizer's email | "sarah@company.com" |
| `attendees` | Array of all attendees | See attendee structure below |

**Attendee Structure** (within `attendees` array):
```json
{
  "emailAddress": {
    "name": "John Client",
    "address": "john@client.com"
  },
  "type": "required",
  "status": {
    "response": "accepted",
    "time": "2026-02-01T09:00:00Z"
  }
}
```

### Meeting Metadata

| Field | Description | Values |
|-------|-------------|--------|
| `is_all_day` | Full day event | true/false |
| `is_cancelled` | Cancellation status | true/false |
| `sensitivity` | Privacy level | "normal", "personal", "private", "confidential" |
| `show_as` | Calendar status | "free", "tentative", "busy", "oof", "workingElsewhere" |
| `importance` | Priority level | "low", "normal", "high" |
| `response_status` | Organizer's response | Object with response/time |
| `created_datetime` | Creation timestamp | "2026-02-01T08:00:00Z" |
| `last_modified_datetime` | Last update time | "2026-02-01T09:30:00Z" |

### Client Information

| Field | Description | Example |
|-------|-------------|---------|
| `first_name` | Client's first name | "John" |
| `last_name` | Client's last name | "Smith" |
| `name` | Full name (fallback) | "John Smith" |
| `email` | Client email address | "john@client.com" |
| `company` | Company name | "Acme Corporation" |
| `phone` | Phone number | "+1234567890" |
| `hubspot_contact_id` | HubSpot contact ID | "12345" |

---

## Make.com Configuration Steps

### 1. Microsoft 365 Calendar - Watch Events Module

- **Connection**: Connect to the bot account (e.g., `bhattacharyabuddhadeb@outlook.com`)
- **Watch For**: New calendar events
- **Limit**: 100 events per execution
- **Output**: All available event fields

### 2. HTTP Module - Make a Request

- **URL**: `https://your-app.onrender.com/outlook-webhook`
- **Method**: POST
- **Headers**:
  - `Content-Type`: `application/json`
- **Body**: Use the JSON payload above

### 3. Field Mapping Tips

- Use the dropdown in Make.com to select fields (avoids typos)
- Most fields are under `event` object from Microsoft 365 module
- `attendees` is an array - pass the whole array as JSON
- Client fields may come from a separate "Get Contact" module or manual mapping

---

## Backend Handling

The backend (`process_outlook_webhook` in `meeting_service.py`) automatically:

1. **Normalizes keys**: Converts "Start time" → "start_time" 
2. **Handles missing fields**: All extra fields are optional
3. **Parses nested data**: Extracts organizer email from nested objects
4. **Stores what it can**: Additional fields are gracefully ignored if not in schema

**No backend code changes needed** to support these extra fields!

---

## Benefits of Enhanced Payload

✅ **Richer AI Context**: Meeting body/agenda helps generate better coaching  
✅ **Deduplication**: `meeting_id` prevents processing same meeting twice  
✅ **Online Meeting Support**: Captures Teams/Zoom links  
✅ **Better CRM Sync**: More data for HubSpot integration  
✅ **Audit Trail**: Created/modified timestamps for debugging  
✅ **Location Awareness**: Physical vs virtual meeting distinction  
✅ **Attendee Insights**: Full list of participants for context

---

## Testing Checklist

- [ ] Create a test meeting with detailed agenda in Outlook
- [ ] Invite both bot accounts
- [ ] Add online meeting link (Teams/Zoom)
- [ ] Check Make.com execution history
- [ ] Verify all fields appear in webhook payload
- [ ] Review backend logs to confirm data received
- [ ] Check if AI coaching references meeting agenda/location

---

## Troubleshooting

### Field not populating in Make.com

- **Cause**: Field may be empty in the actual calendar event
- **Solution**: Create test meeting with all fields filled

### Attendees array is null

- **Cause**: No attendees beyond organizer
- **Solution**: Invite at least one other person to test

### Online meeting URL is empty

- **Cause**: Meeting wasn't created as online meeting
- **Solution**: Use "Teams Meeting" or "Add online meeting" option when creating event

### Payload too large error

- **Cause**: Meeting body or attendee list is very large
- **Solution**: Consider truncating `body` field or limiting attendees

---

## Migration from Minimal Payload

If transitioning from the minimal payload:

1. **Gradual rollout**: Add fields incrementally to test
2. **Monitor logs**: Check for any parsing errors
3. **Backwards compatible**: Old minimal payload still works
4. **Update scenarios**: Update Make.com scenario with new structure
5. **Test thoroughly**: Use test meetings before production

---

## Cost Optimization Notes

While the enhanced payload provides more data:
- Make.com charges by operations, not payload size
- Additional fields = **no extra cost** for the HTTP operation
- May **reduce** future API calls if data is already in payload
- **Net benefit**: More context with same operation cost
