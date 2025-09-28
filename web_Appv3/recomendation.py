import google.generativeai as genai
import requests
import json
from geopy.geocoders import Nominatim
from datetime import datetime
from market_scraper import MarketPriceScraper  # ⬅️ your market scraper

# ==========================
# CONFIGURATION
# ==========================
genai.configure(api_key="AIzaSyCozY_9cxmp9P-xaWPFlpCLRLRKGBBisjc")

# Use Gemini 2.0 Flash
model = genai.GenerativeModel("gemini-2.0-flash")

THINGSPEAK_API_KEY = "R7NLLQNPWE6V6RX7"
THINGSPEAK_CHANNEL_ID = "2828170"

with open('gvtdata.json') as f:
    govt_data = json.load(f)

# ==========================
# HELPERS
# ==========================
def get_current_location():
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
    scraper = MarketPriceScraper()
    result = scraper.get_price_increases()
    if result.get("status") != "success":
        return {
            'Tomato': {'price': 38, 'trend': 'stable'},
            'Brinjal': {'price': 40, 'trend': 'rising'},
            'Chilli': {'price': 42, 'trend': 'rising'},
            'Cotton': {'price': 65, 'trend': 'stable'},
            'Sugarcane': {'price': 30, 'trend': 'falling'}
        }

    market_data = {}
    for row in result["prices"]:
        crop = row["Vegetable"]
        price = row["Current Price"]
        increase = row["Price Increase"]
        trend = "rising" if increase > 0 else "falling" if increase < 0 else "stable"
        market_data[crop] = {"price": price, "trend": trend}
    return market_data

def npk_to_ratio(N, P, K):
    min_val = min(N, P, K)
    return (round(N / min_val, 2), round(P / min_val, 2), round(K / min_val, 2))

def nearest_npk_match(npk_ratio, zone_recs):
    def distance(r1, r2):
        return sum((a - b) ** 2 for a, b in zip(r1, r2)) ** 0.5
    matches = []
    for rec in zone_recs:
        rec_ratio = tuple(map(float, rec['npk_ratio'].split(':')))
        matches.append((distance(npk_ratio, rec_ratio), rec))
    matches.sort(key=lambda x: x[0])
    return [m[1] for m in matches[:10]]

def find_zone_recommendations(npk_ratio, location):
    try:
        zone = 'Southern Plateau' if location['state'] == 'Tamil Nadu' else 'Other Zone'
        matches = []
        for rec in govt_data['fertilizer_recommendations']:
            if rec['agroclimatic_zone'] == zone:
                matches.append({
                    'crop': rec['crop_cropping_system'].split('(')[0].strip(),
                    'npk_ratio': rec['npk_ratio'],
                    'fertilization': rec['fertilization_recommendation']
                })
        return nearest_npk_match(npk_ratio, matches)
    except Exception:
        return []

# ==========================
# MAIN CHANGE: Gemini 2.0 Flash Recommendation
# ==========================
def generate_final_recommendations(npk_data, zone_matches, market_data, location):
    # Convert matches to candidate crops
    candidate_crops = []
    for match in zone_matches:
        crop = match['crop']
        if crop in market_data:
            candidate_crops.append({
                'crop': crop,
                'npk_ratio': match['npk_ratio'],
                'fertilization': match['fertilization'],
                'price': market_data[crop]['price'],
                'trend': market_data[crop]['trend']
            })

    # Build fallback list if no matches
    fallback_crops = ['Tomato', 'Chilli', 'Cotton']

    summary = candidate_crops if candidate_crops else [{"crop": c} for c in fallback_crops]

    # Convert soil NPK to ratio string
    npk_ratio = npk_to_ratio(npk_data['N'], npk_data['P'], npk_data['K'])

    # Gemini prompt
    prompt = f"""
You are an expert agricultural advisor.

Data:
- Location: {location['city']}, {location['state']}
- Soil NPK Ratio: {npk_ratio[0]}:{npk_ratio[1]}:{npk_ratio[2]}
- Candidate Crops: {', '.join([c['crop'] for c in summary])}

Instructions:
1. Recommend exactly 3 crops best suited for the soil and region.
2. Consider soil NPK, regional suitability, and market trends.
3. If insufficient data, use your expertise to fill in 3 crops.
4. Output format: Crop1, Crop2, Crop3
Only give the crop names.
"""

    response = model.generate_content(prompt)
    return response.text.strip()

# ==========================
# PUBLIC FUNCTION for Flask
# ==========================
def get_recommendations():
    location = get_current_location()
    npk_data = fetch_realtime_npk()
    if not npk_data:
        return {"error": "Could not fetch soil NPK data"}, 500

    npk_ratio = npk_to_ratio(npk_data['N'], npk_data['P'], npk_data['K'])
    zone_matches = find_zone_recommendations(npk_ratio, location)
    market_data = fetch_market_data()
    recommendations = generate_final_recommendations(npk_data, zone_matches, market_data, location)

    return {
        "location": f"{location['city']}, {location['state']}",
        "soil_npk": f"{npk_ratio[0]}:{npk_ratio[1]}:{npk_ratio[2]}",
        "timestamp": npk_data['timestamp'],
        "recommended_crops": [c.strip() for c in recommendations.split(',')]
    }

# ==========================
# MAIN APP (Standalone Run)
# ==========================
def main():
    print("🌱 Smart Crop Recommendation System")
    print("==================================")

    data = get_recommendations()
    if isinstance(data, tuple):  # Error case
        print("Error:", data[0]["error"])
        return

    print(f"\n📍 Location: {data['location']}")
    print(f"🧪 Soil NPK Ratio: {data['soil_npk']}")
    print(f"📅 Data Time: {data['timestamp']}")

    print("\n✅ Top Recommended Crops:")
    for i, crop in enumerate(data['recommended_crops'], 1):
        print(f"{i}. {crop}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f"recommendations_{timestamp}.txt", "w") as f:
        f.write(",".join(data['recommended_crops']))

if __name__ == "__main__":
    main()
