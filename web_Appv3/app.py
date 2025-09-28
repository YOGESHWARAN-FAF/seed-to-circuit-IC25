from flask import Flask, request, render_template, jsonify, redirect, url_for, session, Response
import firebase_admin
from firebase_admin import credentials, db
import pyrebase
from flask_cors import CORS
from firebase_admin import auth as Auth
from datetime import datetime
from market_scraper import MarketPriceScraper
import google.generativeai as genai
import json
import re
from farmer_report import FarmerReport
import requests
from geopy.geocoders import Nominatim
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Firebase Web App Configuration
firebaseConfig = {
    "apiKey": os.getenv("FIREBASE_API_KEY", "AIzaSyAzElOieM_Jn81X3_1funjSV07UaM2RI1U"),
    "authDomain": "seed-to-circuit.firebaseapp.com",
    "databaseURL": "https://seed-to-circuit-default-rtdb.firebaseio.com",
    "projectId": "seed-to-circuit",
    "storageBucket": "seed-to-circuit.appspot.com",
    "messagingSenderId": "199581847939",
    "appId": "1:199581847939:web:230624266873dada0766b6",
    "measurementId": "G-9SE7323GZL"
}

# Pyrebase Auth
firebase = pyrebase.initialize_app(firebaseConfig)
auth = firebase.auth()

# Firebase Admin SDK
cred_path = os.path.join(os.path.dirname(__file__), 'config', 'seed-to-circuit-firebase-adminsdk-fbsvc-03825b5a2b.json')
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://seed-to-circuit-default-rtdb.firebaseio.com/'
})

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "pub_96d47a7caf344954b44a696d11eebe59")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyAnsYYAkgOcSXsl71BLymZ6woM0DuxRSHU")
# 🟢 Sign-up Page
@app.route('/sign')
def sign():
    return render_template('sign.html')

# 🔵 Handle Sign-up (Register with Firebase Auth + Save to DB)
@app.route('/sign_in', methods=['POST'])
def signup():
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    state=request.form['state']
    district=request.form['district']
    village=request.form['village']

    if name and email and password and state and district and village:
        try:
            user = auth.create_user_with_email_and_password(email, password)
            uid = user['localId']
            
            # Save user data using UID as key
            ref1 = db.reference(f'signup/users/{uid}')
            ref1.set({
                'name': name,
                'email': email
            })
            ref2=db.reference(f'signup/users/{uid}/location')
            ref2.set({
                'user-location':{
                    'state':state,
                    'district':district,
                    'village':village
                }
            })
            

            return "✅ User signed up successfully!"
        except Exception as e:
            return f"❌ Signup failed: {str(e)}"
        
    return "⚠️ All fields are required"

# 🟢 Login Page
@app.route('/log')
def log():
    return render_template('login.html')

# 🔵 Handle Login
@app.route('/sign-up', methods=['POST'])
def login():
   
        
    try:
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            return jsonify({"message": "Email and password required"}), 400

        user = auth.sign_in_with_email_and_password(email, password)
        token = user['idToken']

        return jsonify({
            "message": "Login successful ✅",
            "idToken": token,
            "email": user.get('email', email)
        }), 200

    except Exception as e:
        return jsonify({
            "message": "Login failed ❌",
            "error": str(e)
        }), 401

seen_entries = set() 
@app.route('/webhook/user_data', methods=['POST', 'OPTIONS'])
def receive_user_data():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'preflight'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response

    try:
        # 🔹 Verify Token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Invalid authorization header'}), 401

        id_token = auth_header.split('Bearer ')[1]
        decoded_token = Auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        print("✅ Verified UID:", uid)

        # 🔹 Parse data
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400

        print("✅ Received data:")
        for key, value in data.items():
            if key != "ai_analysis":
                print(f"  {key}: {value}")
        print("  ai_analysis: [hidden]")

        # 🔹 Duplicate check (using timestamp instead of date)
        unique_key = f"{uid}-{data.get('timestamp', datetime.now().isoformat())}"
        if unique_key in seen_entries:
            print("⚠️ Duplicate detected but still processing...")
        else:
            seen_entries.add(unique_key)

        # 🔹 Store in Firebase
        timestamp = datetime.now().strftime("%Y-%m-%d_%I:%M%p")
        field = data['selected_field']['name']
        reference = db.reference(f'signup/users/{uid}/data/{field}/{timestamp}')
        reference.set({
            'all_fields': data['all_fields'],
            'sensor_data': data['sensor_data'],
            'climate_data': data['climate_data'],
            'historical_climate': data['historical_climate'],
            'disease': data['disease'],
            'ai_result': data['ai_analysis'],
            'medicine': data['medicines']
        })
        print("✅ All data stored under single timestamp node.")

        # 🔹 Prepare WhatsApp-style input
        whatsapp = [{
            'field': field,
            'all_fields': data['all_fields'],
            'sensor_data': data['sensor_data'],
            'climate_data': data['climate_data'],
            'historical_climate': data['historical_climate'],
            'disease': data['disease'],
            'ai_result': data['ai_analysis'],
            'medicine': data['medicines']
        }]

        # 🔹 Generate Gemini report
        farmer = FarmerReport(api_key=os.getenv("GEMINI_API_KEY_2", "AIzaSyCozY_9cxmp9P-xaWPFlpCLRLRKGBBisjc"))
        try:
            report = farmer.generate_report(whatsapp)
            print("Generated Report:", report)
        except Exception as e:
            print(f"❌ Gemini failed: {str(e)}")
            report = {
                "report": {
                    "english": "Error generating report.",
                    "tamil": "அறிக்கை உருவாக்குவதில் பிழை."
                },
                "speech": {
                    "english": "",
                    "tamil": ""
                }
            }

        # 🔹 Send to n8n webhook
        try:
            status, resp = farmer.send_to_webhook(
                report,
                "https://seed-ai.app.n8n.cloud/webhook/5280877d-7f5c-42f5-bee1-1210a79011a1/s2c",  # production
                "https://seed-ai.app.n8n.cloud/webhook-test/5280877d-7f5c-42f5-bee1-1210a79011a1/s2c"  # fallback
            )
            print("Webhook Response:", status, resp)
        except Exception as e:
            print(f"❌ Webhook send failed: {str(e)}")

        # 🔹 Final response
        return jsonify({
            'status': 'success',
            'uid': uid,
            'received_data': {k: v for k, v in data.items() if k != "ai_analysis"}
        }), 200

    except Auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid token'}), 401
    except Auth.ExpiredIdTokenError:
        return jsonify({'error': 'Token expired'}), 401
    except Exception as e:
        print(f"❌ Server Error: {str(e)}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/index')
def index():
    return render_template('index.html')
@app.route('/index/role', methods=['POST', 'GET'])
def role(): 
    if request.method == 'POST':
        response = request.get_json()
        email = response.get('email')  
        token = response.get('token')  
        if email and token:
            return "enable"  
        else:
            return jsonify({
                'msg': 'Login failed, please try again.'
            }), 403  

    return render_template('role.html')

@app.route('/index/role/main/plant/field')  
def field():
    if 'idToken' in session and 'userEmail' in session:
      return render_template('field.html')
    else:
        return redirect(url_for('log'))
       
     
@app.route('/index/role/main/plant/field/1')
def token():
    return render_template('field1.html')

@app.route('/index/role/main', methods=['GET', 'POST'])
def index_role_main():
    if request.method == 'POST':
        token = request.headers.get('Authorization')
        email = request.json.get('email')

        if not token or not email:
            return jsonify({"success": False, "message": "Missing token or email"}), 400

        session['idToken'] = token
        session['userEmail'] = email
        print("Stored in session:", session['userEmail'], session['idToken'])
        return jsonify({"success": True, "message": "User validated"}), 200

    # ✅ If user opens GET /index/role/main directly
    if 'idToken' in session and 'userEmail' in session:
        # Example vegetable market scraper (your existing code)
        scraper = MarketPriceScraper()
        market_data = scraper.get_price_increases()
        vegetable_data = [market_data['prices'][i] for i in range(0, 3)]

        field_list = []  # will store parsed Gemini outputs

        try:
            # Verify Firebase auth
            idtoken = session['idToken'].split('Bearer ')[1]
            decoded_token = Auth.verify_id_token(idtoken)
            uid = decoded_token['uid']
            print("Authenticated UID:", uid)

            # ✅ Fetch latest data for Field 1, 2, 3
            fields = ["Field 1", "Field 2", "Field 3"]
            latest_datas = {}

            for field in fields:
                ref = db.reference(f'signup/users/{uid}/data/{field}')
                snapshots = ref.get()  # dict of timestamps → data
                if snapshots:
                    latest_timestamp = max(snapshots.keys())  # pick latest
                    latest_datas[field] = snapshots[latest_timestamp]
                else:
                    latest_datas[field] = {}

           

            # Gemini setup
            genai.configure(api_key=os.getenv("GEMINI_API_KEY_2", "AIzaSyCozY_9cxmp9P-xaWPFlpCLRLRKGBBisjc"))
            model = genai.GenerativeModel("gemini-2.0-flash")

            # Send all 3 latest fields to Gemini
            prompt = f"""
You are given crop field data: {latest_datas}

Analyse it and return ONLY valid JSON objects (no text before or after). 
Each JSON object must have keys:
'Plant Name', 'Moisture Level', 'Nutrient Level', 'Health Status', 'Needs'.

- 'Plant Name': crop name
- 'Moisture Level': % with % sign
- 'Nutrient Level': % overall (N,P,K,PH considered)
- 'Health Status': Good / Moderate / Poor
- 'Needs': list of recommendations (water, nutrients, medicines, soil amendments) if health is poor recomend 4 to 5 , if health is good recoment the need  2 to 3 (only soil,moister)
-note if you see the disease name(curl_virus) the plant name is =cotton then other vice is ok 
Return one JSON per field.
"""

            response = model.generate_content(prompt)
            field_data_text = response.text

            # Extract all JSON objects
            matches = re.findall(r"\{.*?\}", field_data_text, re.DOTALL)
            for json_str in matches:
                try:
                    data = json.loads(json_str)
                    field_list.append(data)
                except Exception as e:
                    print("Error parsing JSON:", e)

            print("Extracted Field Data List:", field_list)

        except Exception as e:
            print("Authentication failed:", e)

        # ✅ Safely assign each field
        field1_data = field_list[0] if len(field_list) > 0 else {}
        field2_data = field_list[1] if len(field_list) > 1 else {}
        field3_data = field_list[2] if len(field_list) > 2 else {}

        return render_template(
            "main.html",
            email=session['userEmail'],
            vegetable_data=vegetable_data,
            field1_data=field1_data,
            field2_data=field2_data,
            field3_data=field3_data
        )
    else:
        return redirect(url_for('log'))
    

@app.route("/index/role/main/market")
def market():
    scraper = MarketPriceScraper()
    market_data = scraper.get_price_increases()
    if 'idToken' in session and 'userEmail' in session:
      return render_template("market.html", price_data=market_data["prices"])
    else:
        return redirect(url_for('log'))
       

@app.route('/index/role/main/profit-calculator')
def calculator():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("profit_calculator.html")
    else:
        return redirect(url_for('log'))
    

@app.route('/index/role/job-register')
def job_register():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("job_form.html")
    else:
        return redirect(url_for('log'))
@app.route('/register', methods=['POST'])
def register():
    data = {
        "labor_name": request.form['labor_name'],
        "state": request.form['state'],
        "district": request.form['district'],
        "village": request.form['village'],
        "mobile": request.form['mobile'],
        "job_role": request.form['job_role'],
        "wage_per_day": request.form['wage_per_day'],
        "experience": request.form['experience']
    }
    reference=db.reference('job/labor-datas')
    reference.set(data)
    print("Labor Data Received:", data)
    return "✅ Labor Registered Successfully!"
@app.route("/index/role/main/labors", methods=["GET"])
def labor_list():
    reference = db.reference('job/labor-datas')
    labors = reference.get()

    # Convert dict to list
    if labors:
        labors = [labors] if isinstance(labors, dict) and 'labor_name' in labors else list(labors.values())
    else:
        labors = []

    return render_template("labor_find.html", labors=labors)

@app.route('/index/role/main/soil')
def soil():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("soil.html")
    else:
        return redirect(url_for('log'))
@app.route('/index/role/main/profile')
def profile():
    idtoken = session['idToken'].split('Bearer ')[1]
    decoded_token = Auth.verify_id_token(idtoken)
    uid = decoded_token['uid']
    ref = db.reference(f'signup/users/{uid}/data')
    user_data = ref.get()

    all_fields_data = {}

    # convert each field’s timestamps -> list of dicts
    for field, timestamps in user_data.items():
        all_fields_data[field] = []
        for ts, data in timestamps.items():
            data["timestamp"] = ts
            all_fields_data[field].append(data)

    # Debug print to confirm
    print(all_fields_data["Field 2"])

    if 'idToken' in session and 'userEmail' in session:
         return render_template(
        "user.html",
        field2_data=all_fields_data["Field 2"],
        all_fields_data=all_fields_data
        )
    else:
        return redirect(url_for('log'))
@app.route('/index/role/main/sell')
def sell():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("sell.html")
    else:
        return redirect(url_for('log'))    
@app.route('/index/role/main/plant_advicer')
def advicer():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("advicer.html")
    else:
        return redirect(url_for('log')) 
@app.route('/index/role/main/cource-index')
def cource_index():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("cource-index.html")
    else:
        return redirect(url_for('log'))
@app.route('/index/role/main/whatsapp')
def whatsapp():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("whatsapp.html")
    else:
        return redirect(url_for('log'))
@app.route('/webhook/user_data/whatsapp', methods=['POST'])
def connect_whatsapp():
    try:
        # ✅ Verify Token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Invalid authorization header'}), 401

        id_token = auth_header.split('Bearer ')[1]
        decoded_token = Auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        print("✅ Verified UID:", uid)

        # ✅ Get WhatsApp number
        data = request.get_json()
        whatsapp = data.get("whatsapp", "")
        if not whatsapp:
            return jsonify({'error': 'WhatsApp number required'}), 400

        # Store WhatsApp in Firebase under user profile
        db.reference(f'signup/users/{uid}/profile').update({"whatsapp": whatsapp})
        print(f"✅ WhatsApp number {whatsapp} linked for UID {uid}")

        return jsonify({"status": "success", "message": f"WhatsApp {whatsapp} linked successfully!"}), 200

    except Auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid token'}), 401
    except Auth.ExpiredIdTokenError:
        return jsonify({'error': 'Token expired'}), 401
    except Exception as e:
        print(f"❌ Server Error: {str(e)}")
        return jsonify({'error': 'Server error'}), 500
    
@app.route('/index/role/main/quick-commerce')
def quick():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("quick.html")
    else:
        return redirect(url_for('log'))
@app.route('/index/role/wholesale')
def sale():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("wholesale.html")
    else:
        return redirect(url_for('log'))
@app.route('/index/role/wholesale-main')
def sale_main():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("wholesale_maim.html")
    else:
        return redirect(url_for('log'))
@app.route('/index/role/main/voice-agent')
def voice():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("voice_agent.html")
    else:
        return redirect(url_for('log'))
@app.route('/index/role/main/configure')
def configure():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("smartpole.html")
    else:
        return redirect(url_for('log')) 
@app.route('/index/role/main/community')
def community():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("community.html")
    else:
        return redirect(url_for('log'))   
@app.route('/index/role/main/error')
def err():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("err.html")
    else:
        return redirect(url_for('log'))    

@app.route('/index/role/main/datas')
def datas():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("datas.html")
    else:
        return redirect(url_for('log'))   

@app.route('/field-datas', methods=['GET'])
def get_field_datas():
    # 🔒 Get idToken from headers
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({"success": False, "message": "Missing Authorization token"}), 401

    try:
        # Strip "Bearer " if present
        idtoken = token.replace("Bearer ", "")
        decoded_token = Auth.verify_id_token(idtoken)
        uid = decoded_token['uid']
        print("✅ Authenticated UID:", uid)
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid token: {str(e)}"}), 403

    # 🔄 Fetch latest data for fields
    fields = ["Field 1", "Field 2", "Field 3"]
    latest_datas = {}

    for field in fields:
        ref = db.reference(f'signup/users/{uid}/data/{field}')
        snapshots = ref.get()  # { timestamp : data }
        if snapshots:
            latest_timestamp = max(snapshots.keys())  # newest entry
            latest_datas[field] = snapshots[latest_timestamp]
        else:
            latest_datas[field] = {}

    return jsonify({
        "success": True,
        "uid": uid,
        "fields": latest_datas
    }), 200    
# ✅ Route to fetch and translate news
@app.route('/tamil-farming-news')
def tamil_farming_news():
    news_url = f"https://newsdata.io/api/1/latest?apikey={NEWS_API_KEY}&q=agriculture&country=in&category=health,food,environment,domestic,business"
    response = requests.get(news_url)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch news"}), 500

    articles = response.json().get("results", [])[:5]  # Limit to top 5

    tamil_news = []

    for article in articles:
        title = article.get("title", "")
        description = article.get("description", "")

        full_text = f"News Headline:\n{title}\n\nDetails:\n{description}\n\nTranslate this into formal Tamil in a news anchor tone (like Sun News, Thanthi TV). Avoid using *** and unnecessary symbols."

        # Translate using Gemini Flash 2.0
        gemini_response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": full_text}]}]
            }
        )

        if gemini_response.status_code == 200:
            translated_text = gemini_response.json().get("candidates", [])[0].get("content", {}).get("parts", [])[0].get("text", "")
            
            # Remove unnecessary symbols like ***
            clean_text = translated_text.replace("*", "").strip()
            tamil_news.append(clean_text)
        else:
            tamil_news.append("⚠️ தமிழாக்கம் தோல்வியடைந்தது.")

    return render_template("news.html", news_items=tamil_news)
# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY", "AIzaSyAnsYYAkgOcSXsl71BLymZ6woM0DuxRSHU"))
model = genai.GenerativeModel('gemini-2.0-flash')

# Configuration
THINGSPEAK_API_KEY = os.getenv("THINGSPEAK_API_KEY", "R7NLLQNPWE6V6RX7")
THINGSPEAK_CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "2828170")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "647e990dc0844e65a63102000251103")

# Load government recommendations
with open('gvtdata.json') as f:
    govt_data = json.load(f)

def get_current_location():
    """Get approximate location"""
    try:
        geolocator = Nominatim(user_agent="agriculture_app")
        location = geolocator.geocode("Salem, Tamil Nadu")
        return {
            'city': location.address.split(',')[0],
            'state': 'Tamil Nadu',
            'country': 'India',
            'coordinates': (location.latitude, location.longitude)
        }
    except Exception:
        return {
            'city': 'Salem',
            'state': 'Tamil Nadu',
            'country': 'India',
            'coordinates': (11.6643, 78.1460)
        }

def fetch_realtime_npk():
    """Get NPK values from ThingSpeak"""
    try:
        url = f"https://api.thingspeak.com/channels/{THINGSPEAK_CHANNEL_ID}/feeds.json?api_key={THINGSPEAK_API_KEY}&results=1"
        response = requests.get(url)
        data = response.json()
        latest = data['feeds'][0]
        return {
            'N': float(latest['field1']),
            'P': float(latest['field2']),
            'K': float(latest['field3']),
            'timestamp': latest['created_at']
        }
    except Exception:
        return None

def fetch_market_data():
    """Simulated market data"""
    return {
        'Tomato': {'price': 38, 'trend': 'stable'},
        'Brinjal': {'price': 40, 'trend': 'rising'}, 
        'Chilli': {'price': 42, 'trend': 'rising'},
        'Cotton': {'price': 65, 'trend': 'stable'},
        'Sugarcane': {'price': 30, 'trend': 'falling'}
    }

def find_zone_recommendations(npk_ratio, location):
    """Match NPK ratio with government recommendations"""
    try:
        if location['state'] == 'Tamil Nadu':
            zone = 'Southern Plateau'
        else:
            zone = 'Southern Plateau'
        
        matches = []
        for rec in govt_data['fertilizer_recommendations']:
            if rec['agroclimatic_zone'] == zone:
                rec_ratio = tuple(map(float, rec['npk_ratio'].split(':')))
                if len(rec_ratio) == len(npk_ratio):
                    matches.append({
                        'crop': rec['crop_cropping_system'].split('(')[0].strip(),
                        'npk_ratio': rec['npk_ratio'],
                        'fertilization': rec['fertilization_recommendation']
                    })
        return matches[:5]
    except Exception:
        return []

def generate_recommendations(npk_data, zone_matches, market_data, location):
    """Use Gemini to analyze all factors"""
    prompt = f"""
    Analyze these agricultural factors and recommend exactly 3 best crops:
    
    1. Current Soil NPK Ratio: {npk_data['N']}:{npk_data['P']}:{npk_data['K']}
    2. Location: {location['city']}, {location['state']}
    3. Government Recommended Matches: {json.dumps(zone_matches, indent=2)}
    4. Current Market Prices: {json.dumps(market_data, indent=2)}
    
    Respond ONLY with the top 3 crop names in order of recommendation, separated by commas.
    Example: "Tomato, Brinjal, Chilli"
    """
    response = model.generate_content(prompt)
    return response.text.strip()


# ---------------- Flask Routes ----------------

@app.route('/get_recommendations', methods=['GET', 'POST'])
def get_recommendations():
    location = get_current_location()
    npk_data = fetch_realtime_npk()
    
    if not npk_data:
        return jsonify({"error": "Could not fetch soil NPK data"}), 500
    
    npk_ratio = (npk_data['N'], npk_data['P'], npk_data['K'])
    zone_matches = find_zone_recommendations(npk_ratio, location)
    market_data = fetch_market_data()
    recommendations = generate_recommendations(npk_data, zone_matches, market_data, location)
    
    crops = [crop.strip() for crop in recommendations.split(',')]
    
    return jsonify({
        "location": location,
        "soil_npk": npk_data,
        "recommended_crops": crops[:3]  # Return max 3 crops
    })


@app.route('/recommendations')
def show_recommendations():
    response = get_recommendations()   # call API route
    if isinstance(response, tuple):    # error case
        return render_template('error.html', message=response[0].json["error"])
    
    # unwrap Flask Response -> dict
    data = response.get_json()
    
    return render_template('recommendations.html',
                           location=data['location'],
                           soil_npk=data['soil_npk'],
                           crops=data['recommended_crops'])

@app.route('/index/role/main/cultivation')
def cultivation():
    if 'idToken' in session and 'userEmail' in session:
      return render_template("coltivation.html")
    else:
        return redirect(url_for('log'))   

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
    