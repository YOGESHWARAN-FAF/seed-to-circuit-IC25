import requests
from bs4 import BeautifulSoup

class MarketPriceScraper:
    def __init__(self, url="https://vegetablemarketprice.com/market/tamilnadu/today"):
        self.url = url
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }

    def fetch_data(self):
        """Fetch raw table data from website."""
        response = requests.get(self.url, headers=self.headers)
        if response.status_code != 200:
            return {"status": "error", "message": f"Failed to fetch data ({response.status_code})"}

        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find("table")

        if not table:
            return {"status": "error", "message": "No table found on page"}

        rows = table.find_all("tr")
        data_list = []

        for row in rows[1:]:
            cols = row.find_all("td")
            if not cols:
                continue
            data = [col.text.strip() for col in cols]
            data_list.append(data)

        return {"status": "success", "data": data_list}

    def get_price_increases(self):
        """Return dictionary with vegetable prices and increase calculation."""
        result = []
        fetched = self.fetch_data()

        if fetched["status"] != "success":
            return fetched  # return error dictionary directly

        for row in fetched["data"]:
            try:
                vegetable_name = row[1]
                current_price = float(row[2].replace("₹", "").strip())
                previous_price_range = row[3].split(" - ")
                previous_min_price = float(previous_price_range[0].replace("₹", "").strip())

                increase = current_price - previous_min_price

                row_dict = {
                    "Vegetable": vegetable_name,
                    "Current Price": current_price,
                    "Previous Min Price": previous_min_price,
                    "Price Increase": increase
                }
                result.append(row_dict)
            except Exception:
                continue

        return {"status": "success", "prices": result}
