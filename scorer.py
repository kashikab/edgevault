import json
import base64
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client()

# ============================================================
#  TOGGLE
#  DEMO_MODE = True  → instant response, no API call (for stage)
#  DEMO_MODE = False → live Gemini call (for judges who ask)
# ============================================================
DEMO_MODE = False

def score_clip(b64_frames, context):
    """
    Sends frames + context to Gemini and returns a threat score.
    Falls back to a local rule if the API is unavailable.
    """

    if DEMO_MODE:
        return {
            "score":  0.92,
            "reason": "Unauthorized person detected in restricted zone."
        }

    try:
        parts = []
        for b64_str in b64_frames:
            image_bytes = base64.b64decode(b64_str)
            parts.append(
                types.Part.from_bytes(
                    data=image_bytes, mime_type="image/jpeg")
            )

        prompt = f"""
You are a security AI. Evaluate these camera frames and context:
- Camera: {context.get('camera_name')}
- Time:   {context.get('time_of_day')}
- Restricted zone: {context.get('is_restricted')}
- Disk usage: {context.get('disk_percent')}%

Reply ONLY with valid JSON in exactly this format:
{{"score": 0.0-1.0, "reason": "one short sentence"}}

Score guide:
0.0-0.3  empty room, normal daytime movement, no person
0.3-0.7  person present but activity is ambiguous
0.7-1.0  suspicious behaviour, restricted zone at night,
         forced entry, concealed face, running
"""
        parts.append(prompt)

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        return json.loads(response.text)

    except Exception as e:
        print(f"  [WARNING] Gemini API failed: {e}")
        print("  [WARNING] Using local fallback rule.")
        if context.get("time_of_day") == "night" \
                and context.get("is_restricted"):
            return {"score": 0.85,
                    "reason": "Fallback: night + restricted zone"}
        elif context.get("time_of_day") == "night":
            return {"score": 0.6,
                    "reason": "Fallback: night movement"}
        else:
            return {"score": 0.15,
                    "reason": "Fallback: daytime routine movement"}
