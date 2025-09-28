import google.generativeai as genai
import json
import re
import requests


class FarmerReport:
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        # ✅ Configure Gemini
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def generate_report(self, data: dict) -> dict:
        """Generate farmer report (Tamil + English) using Gemini"""
        prompt = f"""
        You are an assistant creating bilingual farmer reports.
        Data: {data}

        1. Generate a farmer-friendly summary report in Tamil and English.
           - Simple, clear words
           - Mention field, sensor data (NPK, pH, moisture), climate, disease, AI result, medicine
           - 100–150 words 

        2. Generate a short speech content (30–40 words) in Tamil + English for audio message.
           - Must be easy for farmers to understand.

        ⚠️ IMPORTANT: 
        - Respond ONLY with valid JSON. 
        - Do not include markdown fences like ```json.
        - Structure must be:
        {{
          "report": {{
            "english": "Full farmer report in English",
            "tamil": "Full farmer report in Tamil"
          }},
          "speech": {{
            "english": "Short speech in English",
            "tamil": "Short speech in Tamil"
          }}
        }}
        """

        response = self.model.generate_content(prompt)
        raw = response.text.strip()

        # 🔹 Ensure only JSON remains
        raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()

        # 🔹 Convert to dict
        return json.loads(raw)

    def send_to_webhook(self, report_dict: dict, webhook_url: str, test_webhook_url: str = None):
        """Send the report to n8n webhook with retry + fallback"""
        try:
            response = requests.post(
                webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(report_dict, ensure_ascii=False).encode("utf-8"),
                timeout=10
            )

            # If webhook inactive (404) and test webhook provided → retry with test
            if response.status_code == 404 and test_webhook_url:
                print("⚠️ Production webhook not active, retrying with test webhook...")
                response = requests.post(
                    test_webhook_url,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(report_dict, ensure_ascii=False).encode("utf-8"),
                    timeout=10
                )

            return response.status_code, response.text

        except Exception as e:
            return 500, f"Error sending to webhook: {str(e)}"
