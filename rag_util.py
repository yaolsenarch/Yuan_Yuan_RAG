import requests
from requests.auth import HTTPBasicAuth
import json
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv
import tiktoken

# 1. this finds the .env file and loads those variables into the environment so we can access them with os.getenv()
load_dotenv()

# 2. Map the environment variables to Python variables
BASE_URL = os.getenv("BASE_URL")
USERNAME=os.getenv("USER")
PASSWORD=os.getenv("PSW")  

# Load the model (this will download ~90MB on first run)
print("Loading Embedding Model...")
model = SentenceTransformer('all-MiniLM-L6-v2')
def clean_confluence_html(raw_html):
    """Simple cleaner to turn Confluence HTML into searchable text."""
    if not raw_html or raw_html == "No content found":
        return ""
    
    # 1. Parse the HTML
    soup = BeautifulSoup(raw_html, "html.parser")
    
    # 2. Remove 'extra' tags that don't add meaning to text
    for extra in soup(["script", "style", "ac:structured-macro"]):
        extra.decompose()
        
    # 3. Get the text, using a newline to separate paragraphs/headers
    # This prevents words from smashing together like 'HeadingParagraph'
    clean_text = soup.get_text(separator="\n")
    
    # 4. Basic whitespace cleanup
    lines = [line.strip() for line in clean_text.splitlines() if line.strip()] # if... is a filter that only includes lines with actual text
    return "\n".join(lines)

def extract_confluence_links(html_content):
    """
    Parses raw HTML to find actual URLs and their labels.
    Specifically targets internal Confluence links.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    found_links = []
    
    # Find all anchor tags with an href
    for a in soup.find_all('a', href=True):
        url = a['href']
        label = a.get_text(strip=True)
        
        # Filter for relevant links (Internal Confluence or SharePoint)
        if "/display/" in url or "/pages/" in url or "sharepoint.com" in url:
            # Ensure relative Confluence links become absolute
            if url.startswith('/'):
                url = "https://confluence.healthpartners.com" + url
                
            found_links.append({
                "label": label,
                "url": url
            })
            
    return found_links

def step_3_pulling_actual_content():
    print("Step 3: Pulling actual content for RAG knowledge base...")
    
    search_url = f"{BASE_URL}/search"
    # We use expand=content.body.storage to reach into that '_expandable' body field
    params = {
        "cql": "favourite = currentUser()",
        "limit": 5,
        "expand": "content.body.storage,body.storage"
    }
    
    response = requests.get(
        search_url,
        auth=HTTPBasicAuth(USERNAME, PASSWORD),
        params=params
    )
    # --Here is the bucket -- 
    extracted_data=[]

    if response.status_code == 200:
        results = response.json().get("results", [])
        for item in results: 
            content_obj = item.get("content", item)
            
            page_id = content_obj.get("id")            
            # 1. Skip if there's no ID (handles those 'None' results you saw)
            if not page_id:
                continue
            # Inside step_3_pulling_actual_content or get_page_by_id
            page_title = content_obj.get("title").replace('\xa0', ' ').strip()
            # Extraction: Successfully fetching HTML using expand=content.body.storage.
            body_html = content_obj.get("body", {}).get("storage", {}).get("value", "")

            # 2. Only add to our list if we actually found text
            if body_html:
                extracted_data.append({
                    "id": page_id,
                    "title": page_title,
                    "html": body_html
                })
                print(f"✅ Added to queue: {page_title}")
    # --- NOW PASS THE BUCKET TO STEP 2 (CLEANING) ---
    return extracted_data 

def process_and_clean(data_list):
    print(f"\nStep 3.1: Cleaning {len(data_list)} pages...")
    cleaned_pages = [] # This is our new "Clean Bucket"
    for page in data_list:
        # Use the cleaning function from the previous turn
        clean_text = clean_confluence_html(page['html'])
        
        # In a real RAG, we'd save 'clean_text' to a database here
        print(f"--- CLEANED: {page['title']} ---")
        print(clean_text[:100] + "...")   
        # We save the cleaned text back into a dictionary
        cleaned_pages.append({
            "id": page['id'],
            "title": page['title'],
            "clean_content": clean_text
        })
        
    # NOW we pass the clean bucket to the next step
    return cleaned_pages

def chunk_text(text, chunk_size=1000, overlap=100):
    """
    Slices text into smaller pieces.
    chunk_size: How many characters per piece
    overlap: How many characters to repeat from the previous piece
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        # Move the start pointer forward, but stay back by the 'overlap' amount
        start += (chunk_size - overlap)
    return chunks

def chunk_text_by_paragraph(text, min_length=50, max_length=1500):
    """
    Improved Strategy: Slices text into logical paragraphs 
    to preserve technical context and code blocks.

    Hardened Chunking: Slices text into logical paragraphs with 
    size guardrails to prevent 'junk' chunks or 'oversized' context.
    """
    # 1. Split by double-newlines (standard paragraph marker)
    raw_paragraphs = text.split('\n\n')
    refined_chunks = []

    for p in raw_paragraphs:
        p = p.strip()
        
        # Guardrail A: Ignore tiny fragments (e.g., "See also:", "Table 1")
        if len(p) < min_length:
            continue
            
        # Guardrail B: Split oversized paragraphs 
        # (prevents embedding truncation in all-MiniLM-L6-v2)
        if len(p) > max_length:
            # If a paragraph is a monster, fallback to a recursive split
            sub_chunks = chunk_text(p, chunk_size=1000, overlap=100)
            refined_chunks.extend(sub_chunks)
        else:
            refined_chunks.append(p)
    
    print(f"   ✂️ Processed {len(raw_paragraphs)} raw segments into {len(refined_chunks)} quality chunks.")
    return refined_chunks
     
def create_embeddings(chunks_list):
    print(f"\nStep 4: Vectorizing {len(chunks_list)} chunks...")
    
    # Extract just the text strings for the model to process in bulk
    texts = [c['chunk_text'] for c in chunks_list]
    
    # SentenceTransformers is fast! It can do the whole list at once.
    vectors = model.encode(texts)
    
    # Put the vectors back into our dictionaries
    for i, chunk in enumerate(chunks_list):
        chunk['vector'] = vectors[i].tolist()
        
    print("✅ All chunks successfully converted to vectors.")
    return chunks_list

def stage_2_crawler(html_content):
    """Finds links to other Confluence pages within the HTML."""
    soup = BeautifulSoup(html_content, "html.parser")
    found_pages = []
    
    # Looking for Confluence-specific link tags
    for link in soup.find_all('ri:page'):
        title = link.get('ri:content-title')
        if title:
            found_pages.append(title)
            
    # Also look for standard anchor tags that look like internal links
    for a in soup.find_all('a', href=True):
        if '/display/' in a['href'] or '/pages/' in a['href']:
            found_pages.append(a.text.strip())
            
    return list(set(found_pages)) # Return unique titles
def process_with_crawler(data_list):
    final_knowledge_base = []
    
    for page in data_list:
        # Standard Clean
        clean_text = clean_confluence_html(page['html'])
        
        # TRIGGER STAGE 2: If this is the "Retirement Home" page
        if "PC SAS Retirement Home" in page['title']:
            print(f"🕵️ Deep Crawl triggered for: {page['title']}")
            linked_titles = stage_2_crawler(page['html'])
            
            for linked_title in linked_titles:
                print(f"   -> Found linked page: {linked_title}")
                # Here you would call your 'get_page_by_title' function 
                # and add its content to final_knowledge_base
        
        # Add the original page data
        final_knowledge_base.append({
            "id": page['id'],
            "title": page['title'],
            "text": clean_text
        })
        
    return final_knowledge_base
def get_child_pages(parent_id):
    """
    Uses the Confluence API to find all direct children of a given page ID.
    It calls the endpoint /content/{id}/child/page to get sub-pages, which is more reliable than parsing HTML for links.
    By default, Confluence is stringy-it only gives you the id and title for each child to keep the response light/fast. It doesnt include HTML content(body)
    """
    print(f"   --> Checking for sub-pages of ID: {parent_id}")
    url = f"{BASE_URL}/content/{parent_id}/child/page"
    
    response = requests.get(
        url,
        auth=HTTPBasicAuth(USERNAME, PASSWORD)
    )
    
    if response.status_code == 200:
        return response.json().get("results", [])
    return []

def get_child_pages_EXPANDED(parent_id):
    """Fetches children AND their content in a single API call."""
    url = f"{BASE_URL}/content/{parent_id}/child/page"
    # We add 'expand=body.storage' to get the HTML content immediately
    params = {"expand": "body.storage", "limit": 25} 
    
    response = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD), params=params)
    
    if response.status_code == 200:
        results = response.json().get("results", [])
        # Transform the results into the format our cleaner expects
        return [{
            "id": r.get("id"),
            "title": r.get("title"),
            "html": r.get("body", {}).get("storage", {}).get("value", "")
        } for r in results]
    return []

def get_page_by_id(page_id):
    """
    Fetches the full HTML content of a specific page by its ID.
    """
    url = f"{BASE_URL}/content/{page_id}"
    params = {"expand": "body.storage"}
    
    response = requests.get(
        url,
        auth=HTTPBasicAuth(USERNAME, PASSWORD),
        params=params
    )
    
    if response.status_code == 200:
        data = response.json()
        return {
            "id": data.get("id"),
            "title": data.get("title").replace('\xa0', ' ').strip() if data.get("title") else "",
            "html": data.get("body", {}).get("storage", {}).get("value", "")
        }
    return None

def get_page_by_title(space_key, title):
    """
    Fetches page content using Space Key and Title (for /display/ links).
    """
    url = f"{BASE_URL}/content"
    params = {
        "spaceKey": space_key,
        "title": title,
        "expand": "body.storage"
    }
    
    response = requests.get(
        url,
        auth=HTTPBasicAuth(USERNAME, PASSWORD),
        params=params
    )
    
    if response.status_code == 200:
        results = response.json().get("results", [])
        if results:
            data = results[0]
            return {
                "id": data.get("id"),
                "title": data.get("title"),
                "html": data.get("body", {}).get("storage", {}).get("value", "")
            }
    return None

def count_tokens(text, model_name="gpt-4o-mini"):
    """Returns the number of tokens in a text string."""
    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        # Fallback if the specific model isn't in the library yet
        encoding = tiktoken.get_encoding("cl100k_base") 
        
    return len(encoding.encode(text))