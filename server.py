from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from playwright.async_api import async_playwright
from langchain.llms import HuggingFaceEndpoint
import json
import sys
import os
import nest_asyncio
import uvicorn
import requests
from bs4 import BeautifulSoup
HUGGINGFACEHUB_API_TOKEN = os.getenv("HUGGINGFACEHUB_API_TOKEN", "")

def initialize_llm():
    return HuggingFaceEndpoint(
        endpoint_url="https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2",
        task="text-generation",
        huggingfacehub_api_token=HUGGINGFACEHUB_API_TOKEN,
    )

# Initialize LLM
llm = initialize_llm()

if sys.platform == "win32":
    asyncio.set_eve

app = FastAPI(
    title="GoMarble Reviews API",
    description="Extract reviews from product pages dynamically",
    version="1.0",
)

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (replace with specific domains for security)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all HTTP headers
)

nest_asyncio.apply()
# Models
class ReviewResponse(BaseModel):
    reviews_count: int
    reviews: list[dict]

# Helper function to dynamically identify CSS selectors using the model
async def identify_selectors(html_content: str):
    print("inside identify")
    prompt = f"""
    Analyze the HTML content of the following product page and identify the CSS selectors that dynamically match the following elements:

    - Reviews container (list of all reviews)
    - Review title (each review's title)
    - Review body (each review's content)
    - Review rating (the rating given by the reviewer)
    - Reviewer name (name of the person who reviewed)
    - Next page (for pagination)

    Please return the CSS selectors as a JSON object. The response should only contain the JSON object without additional explanation.

    HTML Content:
    {html_content}
    """

    response = None
    try:
        # Generate the response using the LLM
        print("before llm")
        response = llm(prompt)["text"]
        print("after llm")
        print(response)
        # Parse the response into JSON
        selectors = json.loads(response)
        return selectors
    except Exception as e:
        raise ValueError(f"Invalid response from model: {response}. Error: {e}")
    
async def get_playwright_instance():
    print("inside get_playwright_instance")
    global async_playwright_instance
    if async_playwright_instance is None:
        async_playwright_instance = async_playwright().start()
    return async_playwright_instance


async def scrape_reviews(url: str):
    print("inside scrape")
    try:
        # Attempt to fetch HTML content using Playwright
        print("inside async")
        playwright = await get_playwright_instance()
        print(playwright)
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        
        all_reviews = []

        while True:
            try:
                # Get page content using Playwright
                html_content = await page.content()
                print("HTML content fetched using Playwright")
            except Exception as e:
                print(f"Playwright failed to fetch HTML content: {e}")
                raise Exception("PlaywrightError")

            # Identify CSS selectors using the model
            selectors = await identify_selectors(html_content)

            if not selectors:
                raise ValueError("Unable to identify CSS selectors for the reviews.")
                
            print("got reviews content")
            # Extract reviews using identified selectors
            reviews = await page.evaluate(f"""
                Array.from(document.querySelectorAll('{selectors['reviews']}')).map(review => ({{ 
                    title: review.querySelector('{selectors["review-title"]}')?.innerText || '', 
                    body: review.querySelector('{selectors['review-body']}')?.innerText || '', 
                    rating: parseInt(review.querySelector('{selectors['review-rating']}')?.innerText || '0'),
                    reviewer: review.querySelector('{selectors['reviewer-name']}')?.innerText || ''
                }}))
            """)

            all_reviews.extend(reviews)

            # Check for next page
            next_page_selector = selectors.get('next-page')
            if next_page_selector:
                next_page = await page.query_selector(next_page_selector)
                if next_page:
                    await next_page.click()
                    await page.wait_for_timeout(2000)  # Wait for the next page to load
                else:
                    break
            else:
                break

        await browser.close()
        return {
            "reviews_count": len(all_reviews),
            "reviews": all_reviews
        }

    except Exception as playwright_error:
        print(f"Playwright encountered an error: {playwright_error}")
        print("Falling back to requests and BeautifulSoup...")

        try:
            # Fallback to using requests and BeautifulSoup
            website_body = requests.get(url)
            website_body.raise_for_status()
            html_content = website_body.text

            print("HTML content fetched using requests")
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract reviews manually using BeautifulSoup and selectors
            selectors = await identify_selectors(html_content)

            if not selectors:
                raise ValueError("Unable to identify CSS selectors for the reviews.")

            reviews = []
            for review in soup.select(selectors['reviews']):
                reviews.append({
                    "title": review.select_one(selectors.get("review-title")).get_text(strip=True) if review.select_one(selectors.get("review-title")) else '',
                    "body": review.select_one(selectors.get("review-body")).get_text(strip=True) if review.select_one(selectors.get("review-body")) else '',
                    "rating": int(review.select_one(selectors.get("review-rating")).get_text(strip=True)) if review.select_one(selectors.get("review-rating")) else 0,
                    "reviewer": review.select_one(selectors.get("reviewer-name")).get_text(strip=True) if review.select_one(selectors.get("reviewer-name")) else ''
                })

            return {
                "reviews_count": len(reviews),
                "reviews": reviews
            }

        except Exception as requests_error:
            print(f"Requests fallback also failed: {requests_error}")
            raise ValueError("Both Playwright and requests methods failed to fetch reviews.")


# Routes
@app.get("/reviews", response_model=ReviewResponse)
async def get_reviews(url: str):
    """
    Extract reviews from the given product page URL.
    """
    try:
        # Sample data simulating what would be scraped
        # reviews_data = {
        #     "reviews_count": 2,
        #     "reviews": [
        #         {
        #             "title": "Great product!",
        #             "body": "I loved this cream. It works as advertised.",
        #             "rating": 5,
        #             "reviewer": "Jane Doe"
        #         },
        #         {
        #             "title": "Not bad",
        #             "body": "Good but a bit overpriced.",
        #             "rating": 3,
        #             "reviewer": "John Smith"
        #         }
        #     ]
        # }
        print(url)
        reviews_data = await scrape_reviews(url)
        print(reviews_data)
        return reviews_data

    except Exception as e:
        raise HTTPException(status_code=501, detail=f"Error scraping reviews: {str(e)}")
    
    
if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)
