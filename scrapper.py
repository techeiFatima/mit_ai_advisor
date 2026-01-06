import requests
from bs4 import BeautifulSoup

# The URL for the MIT Course 6 (EECS) catalog
url = "http://catalog.mit.edu/subjects/6/"

def scrape_mit_courses():
    print("Step 1: Connecting to MIT Catalog...")
    
    # Send a request to the website
    response = requests.get(url)
    
    # Check if the website allowed us in (200 means 'OK')
    if response.status_code != 200:
        print("Failed to get the webpage.")
        return

    print("Step 2: Parsing the website data...")
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # MIT organizes courses in boxes with the class 'courseblock'
    course_blocks = soup.find_all('div', class_='courseblock')
    
    print(f"Step 3: Found {len(course_blocks)} courses. Writing to file...")
    
    with open("mit_courses.txt", "w", encoding='utf-8') as file:
        for block in course_blocks:
            # We extract the text from each block and clean it up
            course_text = block.get_text(separator=" ", strip=True)
            file.write(course_text + "\n" + "-"*50 + "\n")

    print("Task 2 Complete: 'mit_courses.txt' has been created.")

if __name__ == "__main__":
    scrape_mit_courses()