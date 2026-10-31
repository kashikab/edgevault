import json
import base64
from google import genai
from google.genai import types

# Initialize the Gemini client (it will auto-detect GEMINI_API_KEY from your terminal)
client = genai.Client()

def score_clip(b64_frames, context):
    """
    Takes base64 encoded frames from Keshava's vision script and context,
    sends them to Gemini, and returns a strict JSON threat score.
    """
    try:
        # 1. Convert Keshava's base64 strings into raw byte objects for Gemini
        parts = []
        for b64_str in b64_frames:
            image_bytes = base64.b64decode(b64_str)
            parts.append(
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            )
        
        # 2. Build the prompt with your dynamic context
        prompt = f"""
        You are a security AI. Evaluate these camera frames and the following context:
        - Camera Name: {context.get('camera_name')}
        - Time of Day: {context.get('time_of_day')}
        - Restricted Zone: {context.get('is_restricted')}
        - Local Disk Full: {context.get('disk_percent')}%

        Output ONLY valid JSON in this exact format:
        {{"score": 0.0-1.0, "reason": "short sentence"}}
        """
        
        # Add the text prompt to the list of image parts
        parts.append(prompt)

        # 3. Call the API, forcing JSON output
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        # 4. Convert the text response into a Python dictionary
        return json.loads(response.text)
        
    except Exception as e:
        # THE FALLBACK: Prevents the demo from crashing if the API fails
        print(f"[WARNING] API Failed: {e}. Using fallback rule.")
        if context.get('time_of_day') == 'night':
            return {"score": 0.8, "reason": "Fallback: Person detected at night"}
        else:
            return {"score": 0.1, "reason": "Fallback: Daytime routine movement"}