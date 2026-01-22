import urllib.request
import json

url = "https://financialmodelingprep.com/api/v3/profile/GOOGL?apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3"
response = urllib.request.urlopen(url)
data = json.loads(response.read().decode())
print(json.dumps(data, indent=2))
