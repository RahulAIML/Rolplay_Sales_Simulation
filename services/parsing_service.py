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
        
    # 2. Sequential Parsing
    lines = clean_text.split('\n')
    
    mode = "scan" # scan, summary, speaker
    
    parsed_transcript = []
    summary_buffer = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
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
            
        # Check for Speaker Pattern: "Name: Text"
        speaker_match = re.match(r"^([A-Za-z0-9 _'.-]+?)\s*:\s*(.*)", line)
        
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
            if parsed_transcript:
                parsed_transcript[-1] += f" {line}"
            if result["speaker_blocks"]:
                result["speaker_blocks"][-1]["text"] += f" {line}"
                
    result["transcript"] = "\n".join(parsed_transcript)
    if summary_buffer:
        result["summary"] = "\n".join(summary_buffer)
        
    return result
