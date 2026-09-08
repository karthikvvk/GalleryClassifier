import os
import requests
import json
from bs4 import BeautifulSoup

def scrape_bing_images(query="wallpaper", num_images=10, output_dir="wallpapers"):
    """
    Scrapes images from Bing Image Search and saves them to a local directory.
    """
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    url = f"https://www.bing.com/images/search?q={query}&first=1"
    # Use a standard user-agent so Bing doesn't block the request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    print(f"Fetching results for query '{query}'...")
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    
    # Bing stores image metadata in the 'm' attribute of 'a' tags with class 'iusc'
    links = soup.find_all("a", class_="iusc")
    
    count = 0
    for link in links:
        if count >= num_images:
            break
            
        try:
            m_data = json.loads(link.get("m"))
            img_url = m_data.get("murl")
            
            if img_url:
                print(f"Downloading image {count + 1}: {img_url}")
                try:
                    img_response = requests.get(img_url, headers=headers, timeout=10)
                    if img_response.status_code == 200:
                        # Extract the extension from the URL, defaulting to jpg
                        ext = img_url.split(".")[-1].split("?")[0]
                        if len(ext) > 4 or ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                            ext = 'jpg'
                            
                        filename = os.path.join(output_dir, f"{query}_{count + 1}.{ext}")
                        
                        with open(filename, "wb") as f:
                            f.write(img_response.content)
                        count += 1
                    else:
                        print(f"Failed to download {img_url} (Status code: {img_response.status_code})")
                except requests.exceptions.RequestException as e:
                    print(f"Failed to download {img_url}: {e}")
        except Exception as e:
            print(f"Error processing an image link: {e}")

    print(f"\nSuccessfully downloaded {count} images to: {os.path.abspath(output_dir)}")

if __name__ == "__main__":
    # You can change the query and number of images here
    scrape_bing_images(query="memes", num_images=10, output_dir="memes")
