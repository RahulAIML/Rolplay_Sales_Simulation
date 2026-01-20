import re

def parse_raw_meeting_text(raw_text):
    """
    Parses raw meeting text to extract session_id, speaker blocks, and summary.
    
    Args:
        raw_text (str): The raw text payload.
        
    Returns:
        dict: A dictionary containing:
            - session_id (str or None)
            - transcript (str): Combined speaker blocks
            - summary (str or None)
            - speaker_blocks (list of dicts): {speaker, text}
    """
    result = {
        "session_id": None,
        "transcript": "",
        "summary": None,
        "speaker_blocks": []
    }
    
    encoded_text = raw_text.encode('utf-8', 'ignore').decode('utf-8')
    clean_text = encoded_text
    
    # 1. Extract session_id
    req_session = re.search(r"session_id\s*[:\-]\s*([A-Za-z0-9_-]+)", clean_text, re.IGNORECASE)
    if req_session:
        result["session_id"] = req_session.group(1).strip()

    # 1.1 Extract Owner Email
    req_owner = re.search(r"owner\s*[:\-]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", clean_text, re.IGNORECASE)
    if req_owner:
        result["owner_email"] = req_owner.group(1).strip().lower()
        
    # 2. Sequential Parsing
    lines = [line.strip() for line in clean_text.split('\n') if line.strip()]

    # --- SPECIFIC FIX: text aggregator often concatenates ID+Name (e.g. 01KF...Rahul:) ---
    # Check if lines start with a potential ULID (26 chars) or UUID (36 chars) followed immediately by text
    if lines and not result["session_id"]:
        first_line = lines[0]
        # ULID-like (26 chars alphanumeric) or UUID-like
        # We look for a pattern at start of line that looks like an ID
        id_match = re.match(r"^([A-Z0-9]{26}|[a-f0-9-]{36})", first_line, re.IGNORECASE)
        
        if id_match:
            potential_id = id_match.group(1)
            # Verify if this prefix is present in most lines (heuristic to confirm it's an ID, not just random text)
            match_count = sum(1 for line in lines if line.startswith(potential_id))
            if match_count > len(lines) * 0.5 or len(lines) == 1:
                result["session_id"] = potential_id
                # STRIP IT from all lines
                lines = [line[len(potential_id):].strip() for line in lines]

    # If no session_id found and lines exist, try to find a common prefix (e.g. "12345SpeakerA: ...")
    prefix = ""
    if not result["session_id"] and len(lines) > 1:
        # Simple LCP
        s1 = min(lines)
        s2 = max(lines)
        for i, c in enumerate(s1):
            if c != s2[i]:
                prefix = s1[:i]
                break
            else:
                prefix = s1 # if complete match (unlikely for different lines)
        
        if prefix and len(prefix) > 3: # arbitrary sanity check
            # Heuristic: If prefix ends in "Speaker" or "Participant", it might be capturing the name.
            # But we have no safe way to split without data loss. We will use the full prefix as session_id for now.
            result["session_id"] = prefix.strip()

    # --- FALLBACK (For Demo/testing): If no Session ID found, generate one ---
    if not result["session_id"] and lines:
        import uuid
        import time
        # Generate a unique ID so the flow doesn't block
        fallback_id = f"demo_session_{int(time.time())}_{str(uuid.uuid4())[:8]}"
        result["session_id"] = fallback_id


    parsed_transcript = []
    summary_buffer = []
    
    mode = "scan" # scan, summary, speaker

    for line in lines:
        # Check for Session ID line (skip)
        if re.match(r"^session_id\s*[:\-]", line, re.IGNORECASE):
            mode = "scan"
            continue
            
        # Check for Summary Header
        if re.match(r"^Summary\s*[:\-]", line, re.IGNORECASE):
            mode = "summary"
            content = re.sub(r"^Summary\s*[:\-]\s*", "", line, flags=re.IGNORECASE).strip()
            if content:
                summary_buffer.append(content)
            continue
        
        # --- Handle Prefix Stripping ---
        processed_line = line
        if prefix and line.startswith(prefix):
             processed_line = line[len(prefix):].strip()
            
        # Check for Speaker Pattern: "Name: Text"
        # Relaxed Regex: Look for anything ending in a colon at the start of the line
        speaker_match = re.match(r"^([^:\n]{1,50})\s*:\s*(.*)", processed_line)
        
        is_reserved_key = False
        if speaker_match:
            possible_name = speaker_match.group(1).lower()
            if "session_id" in possible_name or "summary" in possible_name:
                is_reserved_key = True
        
        if speaker_match and not is_reserved_key:
            mode = "speaker"
            speaker_name = speaker_match.group(1).strip()
            spoken_text = speaker_match.group(2).strip()
            
            parsed_transcript.append(f"{speaker_name}: {spoken_text}")
            
            result["speaker_blocks"].append({
                "speaker": speaker_name,
                "text": spoken_text
            })
            continue
            
        # Append content based on mode
        if mode == "summary":
            summary_buffer.append(line)
        elif mode == "speaker":
            # Continuation of previous speaker
            if parsed_transcript:
                parsed_transcript[-1] += f" {line}"
            if result["speaker_blocks"]:
                result["speaker_blocks"][-1]["text"] += f" {line}"
        else:
            # Fallback: If we assume "scan" mode but encounter text that isn't metadata, 
            # might be unstructured transcript lines.
            if not parsed_transcript and len(line) > 5:
                 # Treat as anonymous speaker or just text
                 parsed_transcript.append(line)

    result["transcript"] = "\n".join(parsed_transcript)
    if summary_buffer:
        result["summary"] = "\n".join(summary_buffer)
        
    return result
